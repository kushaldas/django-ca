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

"""Shared code for Pydantic-related tests."""
import re
from typing import Any, Dict, List, Tuple, Type, TypeVar, Union

from pydantic import ValidationError

import pytest

from django_ca.pydantic.base import CryptographyModel
from django_ca.pydantic.extensions import ExtensionModel

CryptographyModelTypeVar = TypeVar("CryptographyModelTypeVar", bound=CryptographyModel[Any])
ExtensionModelTypeVar = TypeVar("ExtensionModelTypeVar", bound=ExtensionModel[Any])
ExpectedErrors = List[Tuple[str, Tuple[str, ...], Union[str, "re.Pattern[str]"]]]


def assert_cryptography_model(
    model_class: Type[CryptographyModelTypeVar], parameters: Dict[str, Any], expected: Any
) -> CryptographyModelTypeVar:
    """Test that a cryptography model matches the expected value."""
    model = model_class(**parameters)
    assert model.cryptography == expected
    assert model == model_class.model_validate(expected), (model, model_class.model_validate(expected))
    assert model == model_class.model_validate_json(model.model_dump_json())  # test JSON serialization
    return model  # for any further tests on the model


def assert_validation_errors(
    model_class: Type[CryptographyModelTypeVar], parameters: Dict[str, Any], expected_errors: ExpectedErrors
) -> None:
    """Assertion method to test validation errors."""
    with pytest.raises(ValidationError) as ex_info:
        model_class(**parameters)

    errors = ex_info.value.errors()
    assert len(expected_errors) == len(errors), errors
    for expected, actual in zip(expected_errors, errors):
        assert expected[0] == actual["type"], actual["type"]
        assert expected[1] == actual["loc"], (actual["loc"], actual["msg"])
        if isinstance(expected[2], str):
            assert expected[2] == actual["msg"], actual["msg"]
        else:
            pattern: re.Pattern[str] = expected[2]
            assert pattern.search(actual["msg"]), actual["msg"]