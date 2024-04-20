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

"""Reusable type aliases for Pydantic models."""

import base64
import re
from typing import Annotated, Any, TypeVar

from pydantic import AfterValidator, BeforeValidator, Field, PlainSerializer

from django_ca.pydantic.validators import (
    base64_encoded_str_validator,
    int_to_hex_parser,
    is_power_two_validator,
    non_empty_validator,
    oid_parser,
    oid_validator,
    unique_str_validator,
)

#: A bytes type that validates strings as base64-encoded strings and serializes as such when using JSON.
#:
#: This type differs from ``pydantic.Base64Bytes`` in that bytes are left untouched and strings are decoded
#: `before` the inner validation logic, making this type suitable for strict type validation.
Base64EncodedBytes = Annotated[
    bytes,
    BeforeValidator(base64_encoded_str_validator),
    PlainSerializer(
        lambda value: base64.b64encode(value).decode(encoding="ascii"), return_type=str, when_used="json"
    ),
]

#: A type alias for an integer that is a power of two, e.g. an RSA/DSA KeySize.
#:
#: Note that this type alias does not validate :ref:`settings-ca-min-key-size`, as validators in this module
#: must not use any settings, as this would cause a circular import.
PowerOfTwoTypeAlias = Annotated[int, AfterValidator(is_power_two_validator)]

#: A certificate serial as a hex string, as they are stored in the database.
#:
#: This type will convert integers to hex and upper-case any lower-case strings. The minimum length is 1
#: character, the maximum length is 40 (RFC 5280, section 4.1.2.2 specifies a maximum of 20 octets, which
#: equals 40 characters in hex).
Serial = Annotated[
    str,
    BeforeValidator(int_to_hex_parser),
    AfterValidator(str.upper),
    Field(min_length=1, max_length=40, pattern=re.compile("^[A-F0-9]+$")),
]

NonEmptyOrderedSetTypeVar = TypeVar("NonEmptyOrderedSetTypeVar", bound=list[Any])

OIDType = Annotated[str, BeforeValidator(oid_parser), AfterValidator(oid_validator)]

# A list validated to be non-empty and have a unique set of elements.
NonEmptyOrderedSet = Annotated[
    NonEmptyOrderedSetTypeVar, AfterValidator(unique_str_validator), AfterValidator(non_empty_validator)
]
