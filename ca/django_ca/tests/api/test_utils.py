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


"""Test utility functions."""


from django.test import TestCase

from django_ca.api.utils import create_api_user


class CreateUserTestCase(TestCase):
    """Test create_api_user()."""

    def test_create_basic_user(self) -> None:
        """Test creating a minimal user"""
        user = create_api_user("username", "foobar")
        self.assertEqual(user.username, "username")
        self.assertIs(user.check_password("foobar"), True)
        self.assertIs(user.has_perm("django_ca.view_certificateauthority"), True)
        self.assertIs(user.has_perm("django_ca.view_certificate"), True)
        self.assertIs(user.has_perm("django_ca.sign_certificate"), True)
        self.assertIs(user.has_perm("django_ca.revoke_certificate"), True)

    def test_additional_properties(self) -> None:
        """Test passing additional properties."""

        user = create_api_user("username", "foobar", email="user@example.com")
        self.assertEqual(user.username, "username")
        self.assertIs(user.check_password("foobar"), True)
        self.assertEqual(user.email, "user@example.com")

    def test_no_permissions(self) -> None:
        """Create a user, but rule out all permissions."""
        user = create_api_user(
            "username",
            "foobar",
            view_certificateauthority=False,
            sign_certificate=False,
            view_certificate=False,
            revoke_certificate=False,
        )
        self.assertEqual(user.username, "username")
        self.assertIs(user.check_password("foobar"), True)

        self.assertIs(user.has_perm("django_ca.view_certificateauthority"), False)
        self.assertIs(user.has_perm("django_ca.view_certificate"), False)
        self.assertIs(user.has_perm("django_ca.sign_certificate"), False)
        self.assertIs(user.has_perm("django_ca.revoke_certificate"), False)