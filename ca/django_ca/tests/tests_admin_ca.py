# This file is part of django-ca (https://github.com/mathiasertl/django-ca).
#
# django-ca is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# django-ca is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
# even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with django-ca.  If not,
# see <http://www.gnu.org/licenses/>

"""Test cases for the admin interface for Certificate Authorities."""

from http import HTTPStatus

from django.test import Client
from django.test import override_settings

from ..models import CertificateAuthority
from .base import DjangoCAWithCATestCase
from .base_mixins import AdminTestCaseMixin
from .base_mixins import StandardAdminViewTestCaseMixin


class CertificateAuthorityAdminViewTestCase(StandardAdminViewTestCaseMixin, DjangoCAWithCATestCase):
    """Test CA admin views."""

    model = CertificateAuthority
    media_css = (
        "django_ca/admin/css/base.css",
        "django_ca/admin/css/certificateauthorityadmin.css",
    )

    @override_settings(CA_ENABLE_ACME=False)
    def test_change_view_with_acme(self) -> None:
        """Basic tests but with ACME support disabled."""
        self.test_change_view()


class CADownloadBundleTestCase(AdminTestCaseMixin, DjangoCAWithCATestCase):
    """Tests for downloading the certificate bundle."""

    model = CertificateAuthority
    view_name = "django_ca_certificateauthority_download_bundle"

    @property
    def url(self):
        """Shortcut property to get the bundle URL for the root CA."""
        return self.get_url(self.cas["root"])

    def test_root(self) -> None:
        """Test downloading the bundle for the root CA."""
        self.assertBundle(self.cas["root"], [self.cas["root"]], "root_example_com_bundle.pem")

    def test_child(self) -> None:
        """Test downloading the bundle for a child CA."""
        self.assertBundle(
            self.cas["child"], [self.cas["child"], self.cas["root"]], "child_example_com_bundle.pem"
        )

    def test_invalid_format(self) -> None:
        """Test downloading the bundle in an invalid format."""
        response = self.client.get("%s?format=INVALID" % self.url)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertEqual(response.content, b"")

        # DER is not supported for bundles
        response = self.client.get("%s?format=DER" % self.url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content, b"DER/ASN.1 certificates cannot be downloaded as a bundle.")

    def test_permission_denied(self) -> None:
        """Test downloading without permissions fails."""
        self.user.is_superuser = False
        self.user.save()

        response = self.client.get("%s?format=PEM" % self.url)
        self.assertEqual(response.status_code, HTTPStatus.FORBIDDEN)

    def test_unauthorized(self) -> None:
        """Test viewing as unauthorized viewer."""
        client = Client()
        response = client.get(self.url)
        self.assertRequiresLogin(response)
