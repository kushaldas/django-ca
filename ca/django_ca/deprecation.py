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

"""Deprecation classes in django-ca."""

import functools
import typing
import warnings
from datetime import datetime, timezone as tz
from inspect import signature
from typing import Any, Optional, Union

from cryptography import x509

# IMPORTANT: Do **not** import any module from django_ca here, or you risk circular imports.

F = typing.TypeVar("F", bound=typing.Callable[..., Any])


class RemovedInDjangoCA200Warning(PendingDeprecationWarning):
    """Warning if a feature will be removed in django-ca==2.0."""

    version = "2.0"


class RemovedInDjangoCA210Warning(PendingDeprecationWarning):
    """Warning if a feature will be removed in django-ca==2.1."""

    version = "2.1"


class RemovedInDjangoCA220Warning(PendingDeprecationWarning):
    """Warning if a feature will be removed in django-ca==2.2."""

    version = "2.2"


RemovedInNextVersionWarning = RemovedInDjangoCA200Warning

DeprecationWarningType = Union[
    type[RemovedInDjangoCA200Warning],
    type[RemovedInDjangoCA210Warning],
    type[RemovedInDjangoCA220Warning],
]


def deprecate_argument(
    arg: str, category: DeprecationWarningType, stacklevel: int = 2
) -> typing.Callable[[F], F]:
    """Decorator to mark an argument as deprecated.

    The decorator will issue a warning if the argument is passed to the decorated function, regardless of how
    the argument is passed.
    """

    def decorator_deprecate(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            sig = signature(func)
            bound = sig.bind(*args, **kwargs)
            if arg in bound.arguments:
                warnings.warn(
                    f"Argument {arg} is deprecated and will be removed in django ca {category.version}.",
                    category=category,
                    stacklevel=stacklevel,
                )

            return func(*args, **kwargs)

        return typing.cast(F, wrapper)

    return decorator_deprecate


def deprecate_type(
    arg: str,
    types: Union[type[Any], tuple[type[Any], ...]],
    category: DeprecationWarningType,
    stacklevel: int = 2,
) -> typing.Callable[[F], F]:  # pragma: no cover  # not used at the beginning of 1.24.0 development
    """Decorator to mark a type for an argument as deprecated."""

    def decorator_deprecate(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            sig = signature(func)
            bound = sig.bind(*args, **kwargs)
            if arg in bound.arguments and isinstance(bound.arguments.get(arg), types):
                name = type(bound.arguments.get(arg)).__name__
                warnings.warn(
                    f"Passing {name} for {arg} is deprecated and will be removed in django ca {category.version}.",  # NOQA: E501
                    category=category,
                    stacklevel=stacklevel,
                )

            return func(*args, **kwargs)

        return typing.cast(F, wrapper)

    return decorator_deprecate


# pylint: disable=missing-function-docstring


def not_valid_before(certificate: x509.Certificate) -> datetime:  # noqa: D103
    if hasattr(certificate, "not_valid_before_utc"):  # pragma: only cryptography>=42.0
        return certificate.not_valid_before_utc
    return certificate.not_valid_before.replace(tzinfo=tz.utc)  # pragma: only cryptography<42.0


def not_valid_after(certificate: x509.Certificate) -> datetime:  # noqa: D103
    if hasattr(certificate, "not_valid_after_utc"):  # pragma: only cryptography>=42.0
        return certificate.not_valid_after_utc
    return certificate.not_valid_after.replace(tzinfo=tz.utc)  # pragma: only cryptography<42.0


def crl_next_update(crl: x509.CertificateRevocationList) -> Optional[datetime]:  # noqa: D103
    if hasattr(crl, "next_update_utc"):  # pragma: only cryptography>=42.0
        return crl.next_update_utc
    if crl.next_update is not None:  # pragma: cryptography<42.0 branch
        return crl.next_update.replace(tzinfo=tz.utc)
    return None  # pragma: no cover


def crl_last_update(crl: x509.CertificateRevocationList) -> datetime:  # noqa: D103
    if hasattr(crl, "last_update_utc"):  # pragma: only cryptography>=42.0
        return crl.last_update_utc
    return crl.last_update.replace(tzinfo=tz.utc)  # pragma: only cryptography<42.0


def revoked_certificate_revocation_date(certificate: x509.RevokedCertificate) -> datetime:  # noqa: D103
    if hasattr(certificate, "revocation_date_utc"):  # pragma: only cryptography>=42.0
        return certificate.revocation_date_utc
    return certificate.revocation_date.replace(tzinfo=tz.utc)  # pragma: only cryptography<42.0
