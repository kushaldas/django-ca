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

from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.templatetags.static import static
from django.test import Client
from django.test import override_settings
from django.urls import reverse
from django.utils.encoding import force_str

from .base import DjangoCAWithCATestCase
from .base import certs

User = get_user_model()


class CertificateAuthorityAdminTestMixin:
    """Mixin for test cases in this module."""

    def setUp(self):  # pylint: disable=invalid-name,missing-function-docstring; unittest standard
        self.user = User.objects.create_superuser(username='user', password='password',
                                                  email='user@example.com')
        self.add_url = reverse('admin:django_ca_certificateauthority_add')
        self.changelist_url = reverse('admin:django_ca_certificateauthority_changelist')
        self.client = Client()
        self.client.force_login(self.user)
        super().setUp()

    def assertCSS(self, response, path):  # pylint: disable=invalid-name; unittest standard
        """Assert some CSS path in the given response."""

        css = '<link href="%s" type="text/css" media="all" rel="stylesheet" />' % static(path)
        self.assertInHTML(css, response.content.decode('utf-8'), 1)

    def change_url(self, pk=None):
        """Get change URL for the given object."""
        if pk is None:
            pk = self.cas['root'].pk

        return reverse('admin:django_ca_certificateauthority_change', args=(pk, ))

    def assertChangeResponse(self, response):   # pylint: disable=invalid-name; unittest standard
        """Assert basic characteristics of a change response."""

        self.assertEqual(response.status_code, 200)

        templates = [t.name for t in response.templates]
        self.assertIn('admin/change_form.html', templates)
        self.assertCSS(response, 'django_ca/admin/css/base.css')
        self.assertCSS(response, 'django_ca/admin/css/certificateauthorityadmin.css')

    def assertRequiresLogin(self, response, **kwargs):   # pylint: disable=invalid-name; unittest standard
        """Assert that the response requires a login."""

        expected = '%s?next=%s' % (reverse('admin:login'), quote(response.wsgi_request.get_full_path()))
        self.assertRedirects(response, expected, **kwargs)


class ChangelistTestCase(CertificateAuthorityAdminTestMixin, DjangoCAWithCATestCase):
    """Test the changelist view."""

    def assertResponse(self, response, certificates=None):  # pylint: disable=invalid-name
        """Assert basic class of the response."""

        if certificates is None:
            certificates = []

        self.assertEqual(response.status_code, 200)
        self.assertCSS(response, 'django_ca/admin/css/base.css')
        self.assertCSS(response, 'django_ca/admin/css/certificateauthorityadmin.css')
        self.assertEqual(set(response.context['cl'].result_list), set(certificates))

    def test_get(self):
        """Test a normal view of the change list."""
        response = self.client.get(self.changelist_url)
        self.assertResponse(response, self.cas.values())

    def test_unauthorized(self):
        """Test viewing as unauthorized viewer."""

        client = Client()
        response = client.get(self.changelist_url)
        self.assertRequiresLogin(response)


class ChangeTestCase(CertificateAuthorityAdminTestMixin, DjangoCAWithCATestCase):
    """Test the change view."""

    def test_basic(self):
        """Test that viewing a CA at least does not throw an exception."""
        for ca in self.cas.values():
            response = self.client.get(self.change_url(ca.pk))
            self.assertChangeResponse(response)

    @override_settings(CA_ENABLE_ACME=False)
    def test_with_acme(self):
        """Basic tests but with ACME support disabled."""
        self.test_basic()


class CADownloadBundleTestCase(CertificateAuthorityAdminTestMixin, DjangoCAWithCATestCase):
    """Tests for downloading the certificate bundle."""

    def get_url(self, ca):  # pylint: disable=no-self-use
        """Function to get the bundle URL for the given CA."""
        return reverse('admin:django_ca_certificateauthority_download_bundle', kwargs={'pk': ca.pk})

    @property
    def url(self):
        """Shortcut property to get the bundle URL for the root CA."""
        return self.get_url(ca=self.cas['root'])

    def test_root(self):
        """TEst downloading the bundle for the root CA."""

        filename = 'root_example_com_bundle.pem'
        response = self.client.get('%s?format=PEM' % self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pkix-cert')
        self.assertEqual(response['Content-Disposition'], 'attachment; filename=%s' % filename)
        self.assertEqual(force_str(response.content), certs['root']['pub']['pem'].strip())

    def test_child(self):
        """Test downloading the bundle for a child CA."""

        filename = 'child_example_com_bundle.pem'
        response = self.client.get('%s?format=PEM' % self.get_url(self.cas['child']))
        expected = '%s\n%s' % (certs['child']['pub']['pem'].strip(), certs['root']['pub']['pem'].strip())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pkix-cert')
        self.assertEqual(response['Content-Disposition'], 'attachment; filename=%s' % filename)
        self.assertEqual(force_str(response.content), expected)

    def test_invalid_format(self):
        """Test downloading the bundle in an invalid format."""

        response = self.client.get('%s?format=INVALID' % self.url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content, b'')

        # DER is not supported for bundles
        response = self.client.get('%s?format=DER' % self.url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content, b'DER/ASN.1 certificates cannot be downloaded as a bundle.')

    def test_unauthorized(self):
        """Test viewing as unauthorized viewer."""

        client = Client()
        response = client.get(self.url)
        self.assertRequiresLogin(response)
