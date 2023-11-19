# This file is part of django-ca (https://github.com/mathiasertl/django-ca).
#
# django-ca is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# django-ca is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the
# implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License along with django-ca. If not, see
# <http://www.gnu.org/licenses/>.

# pylint: disable=redefined-outer-name  # requested pytest fixtures show up this way.

"""Test the signing certificates via the API."""

import ipaddress
from datetime import timedelta
from http import HTTPStatus
from typing import Any, Dict, Optional, Tuple, Type

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import ExtendedKeyUsageOID, ExtensionOID, NameOID

from django.contrib.auth.models import AbstractUser
from django.db.models import Model
from django.test.client import Client
from django.urls import reverse, reverse_lazy
from django.utils import timezone

import pytest
from freezegun import freeze_time

from django_ca import ca_settings, constants
from django_ca.models import Certificate, CertificateAuthority, CertificateOrder
from django_ca.tests.api.conftest import APIPermissionTestBase
from django_ca.tests.base.constants import CERT_DATA, TIMESTAMPS
from django_ca.tests.base.typehints import CaptureOnCommitCallbacks, HttpResponse
from django_ca.tests.base.utils import (
    authority_information_access,
    certificate_policies,
    crl_distribution_points,
    distribution_point,
    dns,
    extended_key_usage,
    freshest_crl,
    ip,
    iso_format,
    key_usage,
    ocsp_no_check,
    rdn,
    subject_alternative_name,
    tls_feature,
    uri,
)

path = reverse_lazy("django_ca:api:sign_certificate", kwargs={"serial": CERT_DATA["root"]["serial"]})
default_subject = [{"oid": NameOID.COMMON_NAME.dotted_string, "value": "api.example.com"}]


@pytest.fixture(scope="module")
def api_permission() -> Tuple[Type[Model], str]:
    """Fixture for the permission required by this view."""
    return Certificate, "sign_certificate"


@pytest.fixture()
def expected_response() -> Dict[str, Any]:
    """Fixture for the non-dynamic parts of the expected response."""
    return {
        "created": iso_format(TIMESTAMPS["everything_valid"]),
        "updated": iso_format(TIMESTAMPS["everything_valid"]),
        "status": "pending",
        "user": "user",
        "serial": None,
    }


def request(client: Client, data: Dict[str, Any]) -> HttpResponse:
    """Shortcut to run a request."""
    return client.post(path, data, content_type="application/json")


def sign_certificate(
    django_capture_on_commit_callbacks: CaptureOnCommitCallbacks,
    user: AbstractUser,
    client: Client,
    ca: CertificateAuthority,
    data: Dict[str, Any],
    expected_response: Dict[str, Any],
    expected_algorithm: Optional[hashes.HashAlgorithm] = None,
) -> Certificate:
    """Common function to issue a certificate signing request."""
    # Add CSR to data
    data["csr"] = CERT_DATA["root-cert"]["csr"]["pem"]

    # Issue a signing request
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = request(client, data)
        assert response.status_code == HTTPStatus.OK, response.content

        # Get order before on_commit callbacks are called to test pending state
        order: CertificateOrder = CertificateOrder.objects.get(certificate_authority=ca)
        assert order.status == CertificateOrder.STATUS_PENDING
        assert order.certificate is None
        assert order.user == user

    # Make sure that there was a callback
    assert len(callbacks) == 1

    # Test that the response looks okay
    expected_response["slug"] = order.slug
    assert response.json() == expected_response

    # Get certificate and validate some properties
    cert: Certificate = Certificate.objects.get(ca=ca, cn="api.example.com")
    assert cert.profile == data.get("profile", ca_settings.CA_DEFAULT_PROFILE)
    assert cert.autogenerated is data.get("autogenerated", False)
    assert cert.algorithm == expected_algorithm or ca.algorithm

    # Test the order in its final state
    order.refresh_from_db()
    assert order.status == CertificateOrder.STATUS_ISSUED
    assert order.certificate == cert

    # Get updated order object
    order_path = reverse(
        "django_ca:api:get_certificate_order", kwargs={"serial": ca.serial, "slug": order.slug}
    )
    order_response = client.get(order_path)

    # Update expected response with dynamic data
    expected_response["status"] = "issued"
    expected_response["serial"] = cert.serial

    assert order_response.status_code == HTTPStatus.OK, response.content
    assert order_response.json() == expected_response

    return cert


@freeze_time(TIMESTAMPS["everything_valid"])
def test_sign_ca_values(
    api_user: AbstractUser,
    api_client: Client,
    usable_root: CertificateAuthority,
    expected_response: Dict[str, Any],
    django_capture_on_commit_callbacks: CaptureOnCommitCallbacks,
) -> None:
    """Test that CA extensions are added."""
    cert = sign_certificate(
        django_capture_on_commit_callbacks,
        api_user,
        api_client,
        ca=usable_root,
        data={"subject": default_subject},
        expected_response=expected_response,
    )

    extensions = cert.x509_extensions

    # Test Authority Information Access extension
    assert extensions[ExtensionOID.AUTHORITY_INFORMATION_ACCESS] == authority_information_access(
        ca_issuers=[uri(usable_root.issuer_url)], ocsp=[uri(usable_root.ocsp_url)]
    )

    # Test CRL Distribution Points extension
    assert extensions[ExtensionOID.CRL_DISTRIBUTION_POINTS] == crl_distribution_points(
        distribution_point(full_name=[uri(usable_root.crl_url)])
    )


@freeze_time(TIMESTAMPS["everything_valid"])
def test_private_key_unavailable(
    api_user: AbstractUser,
    api_client: Client,
    root: CertificateAuthority,
    expected_response: Dict[str, Any],
    django_capture_on_commit_callbacks: CaptureOnCommitCallbacks,
) -> None:
    """Test the error when no private key is available."""
    with django_capture_on_commit_callbacks() as callbacks:
        response = request(
            api_client, {"csr": CERT_DATA["root-cert"]["csr"]["pem"], "subject": default_subject}
        )

        # Get order before on_commit callbacks are called to test pending state
        order: CertificateOrder = CertificateOrder.objects.get(certificate_authority=root)
        assert order.status == CertificateOrder.STATUS_PENDING
        assert order.certificate is None
        assert order.user == api_user

    # Make sure that there was a callback
    assert len(callbacks) == 1

    # Test that the response looks okay
    assert response.status_code == HTTPStatus.OK, response.content
    expected_response["slug"] = order.slug
    assert response.json() == expected_response


@freeze_time(TIMESTAMPS["everything_valid"])
def test_sign_certificate_with_parameters(
    api_user: AbstractUser,
    api_client: Client,
    usable_root: CertificateAuthority,
    expected_response: Dict[str, Any],
    django_capture_on_commit_callbacks: CaptureOnCommitCallbacks,
) -> None:
    """Test signing with parameters."""
    expires = timezone.now() + timedelta(days=73)

    cert = sign_certificate(
        django_capture_on_commit_callbacks,
        api_user,
        api_client,
        ca=usable_root,
        data={
            "subject": default_subject,
            "autogenerated": True,
            "profile": "server",
            "expires": iso_format(expires),
            "algorithm": "SHA3/384",
        },
        expected_response=expected_response,
        expected_algorithm=hashes.SHA3_384(),
    )

    assert cert.not_after == expires


@freeze_time(TIMESTAMPS["everything_valid"])
def test_sign_certificate_with_extensions(
    api_user: AbstractUser,
    api_client: Client,
    usable_root: CertificateAuthority,
    expected_response: Dict[str, Any],
    django_capture_on_commit_callbacks: CaptureOnCommitCallbacks,
) -> None:
    """Test signing certificates with extensions."""
    cert = sign_certificate(
        django_capture_on_commit_callbacks,
        api_user,
        api_client,
        ca=usable_root,
        data={
            "subject": default_subject,
            "extensions": {
                "authority_information_access": {
                    "value": {
                        "issuers": ["http://api.issuer.example.com"],
                        "ocsp": ["http://api.ocsp.example.com"],
                    },
                },
                "certificate_policies": {
                    "value": [
                        {"policy_identifier": "1.1.1"},
                        {
                            "policy_identifier": "1.3.3",
                            "policy_qualifiers": [
                                "A policy qualifier as a string",
                                {
                                    "explicit_text": "An explicit text",
                                    "notice_reference": {
                                        "organization": "some org",
                                        "notice_numbers": [1, 2, 3],
                                    },
                                },
                            ],
                        },
                    ]
                },
                "crl_distribution_points": {
                    "value": [
                        {"full_name": ["http://api.crl1.example.com"]},
                        {
                            "full_name": ["http://api.crl2.example.com"],
                            "crl_issuer": ["http://api.crl2.example.com"],
                            "reasons": ["keyCompromise"],
                        },
                        {
                            "relative_name": [
                                {"oid": NameOID.COMMON_NAME.dotted_string, "value": "example.com"}
                            ]
                        },
                    ]
                },
                "extended_key_usage": {"value": ["serverAuth", "1.2.3"]},
                "freshest_crl": {"value": [{"full_name": ["http://api.freshest-crl.example.com"]}]},
                "key_usage": {"value": ["keyEncipherment"]},
                "ocsp_no_check": {},
                "subject_alternative_name": {
                    "critical": not constants.EXTENSION_DEFAULT_CRITICAL[
                        ExtensionOID.SUBJECT_ALTERNATIVE_NAME
                    ],
                    "value": ["DNS:example.com", "IP:127.0.0.1"],
                },
                "tls_feature": {"value": ["OCSPMustStaple"]},
            },
        },
        expected_response=expected_response,
    )

    # Test extensions
    exts = cert.x509_extensions

    # Test Authority Information Access extension
    assert exts[ExtensionOID.AUTHORITY_INFORMATION_ACCESS] == authority_information_access(
        ca_issuers=[uri("http://api.issuer.example.com")], ocsp=[uri("http://api.ocsp.example.com")]
    )

    # Test Certificate Policies extension
    assert exts[ExtensionOID.CERTIFICATE_POLICIES] == certificate_policies(
        x509.PolicyInformation(policy_identifier=x509.ObjectIdentifier("1.1.1"), policy_qualifiers=None),
        x509.PolicyInformation(
            policy_identifier=x509.ObjectIdentifier("1.3.3"),
            policy_qualifiers=[
                "A policy qualifier as a string",
                x509.UserNotice(
                    notice_reference=x509.NoticeReference(organization="some org", notice_numbers=[1, 2, 3]),
                    explicit_text="An explicit text",
                ),
            ],
        ),
    )

    # Test CRL Distribution Points extension
    assert exts[ExtensionOID.CRL_DISTRIBUTION_POINTS] == crl_distribution_points(
        distribution_point(full_name=[uri("http://api.crl1.example.com")]),
        distribution_point(
            full_name=[uri("http://api.crl2.example.com")],
            crl_issuer=[uri("http://api.crl2.example.com")],
            reasons=frozenset([x509.ReasonFlags.key_compromise]),
        ),
        distribution_point(relative_name=rdn([(NameOID.COMMON_NAME, "example.com")])),
    )

    # Test Extended Key Usage extension
    assert exts[ExtensionOID.EXTENDED_KEY_USAGE] == extended_key_usage(
        x509.ObjectIdentifier("1.2.3"), ExtendedKeyUsageOID.SERVER_AUTH
    )

    # Test Freshest CRL extension
    assert exts[ExtensionOID.FRESHEST_CRL] == freshest_crl(
        distribution_point(full_name=[uri("http://api.freshest-crl.example.com")])
    )

    # Test Key Usage extension
    assert exts[ExtensionOID.KEY_USAGE] == key_usage(key_encipherment=True)

    # Test OCSPNoCheck extension
    assert exts[ExtensionOID.OCSP_NO_CHECK] == ocsp_no_check()

    # Test Subject Alternative Name extension
    assert exts[ExtensionOID.SUBJECT_ALTERNATIVE_NAME] == subject_alternative_name(
        dns("example.com"), ip(ipaddress.IPv4Address("127.0.0.1")), critical=True
    )

    # Test TLSFeature extension
    assert exts[ExtensionOID.TLS_FEATURE] == tls_feature(x509.TLSFeatureType.status_request)


@freeze_time(TIMESTAMPS["everything_valid"])
def test_sign_certificate_with_subject_alternative_name(
    api_user: AbstractUser,
    api_client: Client,
    usable_root: CertificateAuthority,
    expected_response: Dict[str, Any],
    django_capture_on_commit_callbacks: CaptureOnCommitCallbacks,
) -> None:
    """Test signing certificates with an additional subject alternative name."""
    cert = sign_certificate(
        django_capture_on_commit_callbacks,
        api_user,
        api_client,
        ca=usable_root,
        data={
            "subject": default_subject,
            "extensions": {
                "subject_alternative_name": {
                    "critical": not constants.EXTENSION_DEFAULT_CRITICAL[
                        ExtensionOID.SUBJECT_ALTERNATIVE_NAME
                    ],
                    "value": ["DNS:example.com", "IP:127.0.0.1"],
                },
            },
        },
        expected_response=expected_response,
    )

    # Test SubjectAlternativeName extension
    extensions = cert.x509_extensions

    # Test Subject Alternative Name extension
    assert extensions[ExtensionOID.SUBJECT_ALTERNATIVE_NAME] == subject_alternative_name(
        dns("example.com"), ip(ipaddress.IPv4Address("127.0.0.1")), critical=True
    )


@pytest.mark.usefixtures("tmpcadir")
@freeze_time(TIMESTAMPS["everything_valid"])
def test_crldp_with_full_name_and_relative_name(api_client: Client) -> None:
    """Test sending a CRL Distribution point with a full_name and a relative_name."""
    response = request(
        api_client,
        {
            "csr": CERT_DATA["root-cert"]["csr"]["pem"],
            "subject": default_subject,
            "extensions": {
                "crl_distribution_points": {
                    "value": [
                        {
                            "full_name": ["http://api.crl1.example.com"],
                            "relative_name": [
                                {"oid": NameOID.COMMON_NAME.dotted_string, "value": "example.com"}
                            ],
                        },
                    ]
                },
            },
        },
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.json()
    assert response.json() == {
        "detail": [
            {
                "ctx": {"error": "Distribution point must contain either full_name OR relative_name."},
                "loc": ["body", "data", "extensions", "crl_distribution_points", "value", 0],
                "msg": "Value error, Distribution point must contain either full_name OR relative_name.",
                "type": "value_error",
            }
        ]
    }


@pytest.mark.usefixtures("tmpcadir")
@freeze_time(TIMESTAMPS["everything_valid"])
def test_crldp_with_no_full_name_or_relative_name(api_client: Client) -> None:
    """Test sending a CRL Distribution point with neither a full name nor a relative name."""
    response = request(
        api_client,
        {
            "csr": CERT_DATA["root-cert"]["csr"]["pem"],
            "subject": default_subject,
            "extensions": {
                "crl_distribution_points": {
                    "value": [
                        {},
                    ]
                },
            },
        },
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.json()
    assert response.json() == {
        "detail": [
            {
                "ctx": {"error": "Distribution point must contain one of full_name OR relative_name."},
                "loc": ["body", "data", "extensions", "crl_distribution_points", "value", 0],
                "msg": "Value error, Distribution point must contain one of full_name OR relative_name.",
                "type": "value_error",
            }
        ]
    }


@pytest.mark.usefixtures("tmpcadir")
@freeze_time(TIMESTAMPS["everything_valid"])
def test_with_invalid_key_usage(api_client: Client) -> None:
    """Test sending an invalid key usage."""
    response = request(
        api_client,
        {
            "csr": CERT_DATA["root-cert"]["csr"]["pem"],
            "subject": default_subject,
            "extensions": {"key_usage": {"value": ["unknown"]}},
        },
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.json()
    assert response.json() == {
        "detail": [
            {
                "ctx": {"error": "unknown: Invalid key usage."},
                "loc": ["body", "data", "extensions", "key_usage", "value"],
                "msg": "Value error, unknown: Invalid key usage.",
                "type": "value_error",
            }
        ]
    }


@pytest.mark.usefixtures("tmpcadir", "usable_root")
@freeze_time(TIMESTAMPS["everything_expired"])
def test_expired_ca(api_client: Client) -> None:
    """Test that you can *not* sign a certificate for an expired CA."""
    response = request(api_client, {"csr": CERT_DATA["root-cert"]["csr"]["pem"], "subject": default_subject})
    assert response.status_code == HTTPStatus.NOT_FOUND, response.content
    assert response.json() == {"detail": "Not Found"}, response.json()


class TestPermissions(APIPermissionTestBase):
    """Test permissions for this view."""

    path = path

    def request(self, client: Client) -> HttpResponse:
        return request(client, {"csr": CERT_DATA["root-cert"]["csr"]["pem"], "subject": default_subject})
