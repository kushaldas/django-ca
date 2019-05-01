"""
This file demonstrates writing tests using the unittest module. These will pass
when you run "manage.py test".

Replace this with more appropriate tests for your application.
"""

import inspect
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from datetime import timedelta

import six
from OpenSSL.crypto import FILETYPE_PEM
from OpenSSL.crypto import X509Store
from OpenSSL.crypto import X509StoreContext
from OpenSSL.crypto import load_certificate

import cryptography
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import ExtensionOID

from django.conf import settings
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.core.management import ManagementUtility
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.test.utils import override_settings as _override_settings
from django.utils.six import StringIO
from django.utils.six.moves import reload_module

from .. import ca_settings
from ..extensions import AuthorityInformationAccess
from ..extensions import AuthorityKeyIdentifier
from ..extensions import BasicConstraints
from ..extensions import ExtendedKeyUsage
from ..extensions import Extension
from ..extensions import KeyUsage
from ..extensions import ListExtension
from ..extensions import SubjectAlternativeName
from ..extensions import SubjectKeyIdentifier
from ..models import Certificate
from ..models import CertificateAuthority
from ..profiles import get_cert_profile_kwargs
from ..signals import post_create_ca
from ..signals import post_issue_cert
from ..signals import post_revoke_cert
from ..subject import Subject
from ..utils import OID_NAME_MAPPINGS
from ..utils import ca_storage
from ..utils import x509_name

if six.PY2:  # pragma: only py2
    from mock import Mock
    from mock import patch

    from testfixtures import LogCapture  # for capturing logging
else:  # pragma: only py3
    from unittest.mock import Mock
    from unittest.mock import patch

#if ca_settings.CRYPTOGRAPHY_HAS_PRECERT_POISON:  # pragma: no branch, pragma: only cryptography>=2.4
#    from ..extensions import PrecertPoison


def _load_key(data):
    basedir = data.get('basedir', settings.FIXTURES_DIR)
    path = os.path.join(basedir, data['key_filename'])

    with open(path, 'rb') as stream:
        raw = stream.read()

    parsed = serialization.load_pem_private_key(raw, password=data.get('password'), backend=default_backend())
    return {
        'pem': raw.decode('utf-8'),
        'parsed': parsed,
    }


def _load_csr(data):
    basedir = data.get('basedir', settings.FIXTURES_DIR)
    path = os.path.join(basedir, data['csr_filename'])

    with open(path, 'r') as stream:
        raw = stream.read().strip()

    return {
        'pem': raw,
    }


def _load_pub(data):
    basedir = data.get('basedir', settings.FIXTURES_DIR)
    path = os.path.join(basedir, data['pub_filename'])

    with open(path, 'rb') as stream:
        pem = stream.read()

    return {
        'pem': pem.decode('utf-8'),
        'parsed': x509.load_pem_x509_certificate(pem, default_backend()),
    }


cryptography_version = tuple([int(t) for t in cryptography.__version__.split('.')[:2]])

with open(os.path.join(settings.FIXTURES_DIR, 'cert-data.json')) as stream:
    _fixture_data = json.load(stream)
certs = _fixture_data.get('certs')

# Update some data from contrib (data is not in cert-data.json, since we don't generate them)
certs['multiple_ous'] = {
    'name': 'multiple_ous',
    'key_filename': False,
    'csr_filename': False,
    'pub_filename': os.path.join('contrib', 'multiple_ous_and_no_ext.pem'),
    'cat': 'contrib',
    'type': 'cert',
    'valid_from': '1998-05-18 00:00:00',
    'valid_until': '2028-08-01 23:59:59',
}
certs['cloudflare_1'] = {
    'name': 'cloudflare_1',
    'key_filename': False,
    'csr_filename': False,
    'pub_filename': os.path.join('contrib', 'cloudflare_1.pem'),
    'cat': 'contrib',
    'type': 'cert',
    'valid_from': '2018-07-18 00:00:00',
    'valid_until': '2019-01-24 23:59:59',
}

# Calculate some fixted timestamps that we reuse throughout the tests
timestamps = {
    'base': datetime.strptime(_fixture_data['timestamp'], '%Y-%m-%d %H:%M:%S'),
}
timestamps['before_everything'] = timestamps['base'] - timedelta(days=0)
timestamps['before_child'] = timestamps['base'] - timedelta(days=1)
timestamps['everything_valid'] = timestamps['base'] + timedelta(days=30)
timestamps['everything_expired'] = timestamps['base'] + timedelta(days=365 * 20)

for cert_name, cert_data in certs.items():
    if cert_data.get('password'):
        cert_data['password'] = cert_data['password'].encode('utf-8')
    if cert_data['cat'] == 'sphinx-contrib':
        cert_data['basedir'] = os.path.join(settings.SPHINX_FIXTURES_DIR, cert_data['type'])

    # Load data from files
    if cert_data['key_filename'] is not False:
        cert_data['key'] = _load_key(cert_data)
    if cert_data['csr_filename'] is not False:
        cert_data['csr'] = _load_csr(cert_data)
    cert_data['pub'] = _load_pub(cert_data)

    # parse some data from the dict
    cert_data['valid_from'] = datetime.strptime(cert_data['valid_from'], '%Y-%m-%d %H:%M:%S')
    cert_data['valid_until'] = datetime.strptime(cert_data['valid_until'], '%Y-%m-%d %H:%M:%S')
    cert_data['valid_from_short'] = cert_data['valid_from'].strftime('%Y-%m-%d %H:%M')
    cert_data['valid_until_short'] = cert_data['valid_until'].strftime('%Y-%m-%d %H:%M')

    # parse extensions
    if cert_data.get('authority_key_identifier'):
        cert_data['authority_key_identifier'] = AuthorityKeyIdentifier(cert_data['authority_key_identifier'])
    if cert_data.get('subject_key_identifier'):
        cert_data['subject_key_identifier'] = SubjectKeyIdentifier(cert_data['subject_key_identifier'])
    if cert_data.get('basic_constraints'):
        cert_data['basic_constraints'] = BasicConstraints(cert_data['basic_constraints'])
    if cert_data.get('extended_key_usage'):
        cert_data['extended_key_usage'] = ExtendedKeyUsage(cert_data['extended_key_usage'])
    if cert_data.get('key_usage'):
        cert_data['key_usage'] = KeyUsage(cert_data['key_usage'])
    if cert_data.get('authority_information_access'):
        cert_data['authority_information_access'] = AuthorityInformationAccess(
            cert_data['authority_information_access'])
    if cert_data.get('subject_alternative_name'):
        cert_data['subject_alternative_name'] = SubjectAlternativeName(cert_data['subject_alternative_name'])

print(certs['root'])

if certs and ca_settings.CRYPTOGRAPHY_HAS_PRECERT_POISON:  # pragma: no branch, pragma: only cryptography>=2.4
    pass  # not there yet
    #certs['cert_all']['precert_poison'] = PrecertPoison()
    #certs['cloudflare_1']['precert_poison'] = PrecertPoison()


class override_settings(_override_settings):
    """Enhance override_settings to also reload django_ca.ca_settings.

    .. WARNING:: When using this class as a class decorator, the decorated class must inherit from
       :py:class:`~django_ca.tests.base.DjangoCATestCase`.
    """

    def __call__(self, test_func):
        if inspect.isclass(test_func) and not issubclass(test_func, DjangoCATestCase):
            raise ValueError("Only subclasses of DjangoCATestCase can use override_settings")
        inner = super(override_settings, self).__call__(test_func)
        return inner

    def save_options(self, test_func):
        super(override_settings, self).save_options(test_func)
        reload_module(ca_settings)

    def enable(self):
        super(override_settings, self).enable()

        try:
            reload_module(ca_settings)
        except Exception:  # pragma: no cover
            # If an exception is thrown reloading ca_settings, we disable everything again.
            # Otherwise an exception in ca_settings will cause overwritten settings to persist
            # to the next tests.
            super(override_settings, self).disable()
            reload_module(ca_settings)
            raise

    def disable(self):
        super(override_settings, self).disable()
        reload_module(ca_settings)


@contextmanager
def mock_cadir(path):
    """Contextmanager to set the CA_DIR to a given path without actually creating it."""
    with override_settings(CA_DIR=path), \
            patch.object(ca_storage, 'location', path), \
            patch.object(ca_storage, '_location', path):
        yield


class override_tmpcadir(override_settings):
    """Sets the CA_DIR directory to a temporary directory.

    .. NOTE: This also takes any additional settings.
    """

    def __call__(self, test_func):
        if not inspect.isfunction(test_func):
            raise ValueError("Only functions can use override_tmpcadir()")
        return super(override_tmpcadir, self).__call__(test_func)

    def enable(self):
        self.options['CA_DIR'] = tempfile.mkdtemp()

        # copy CAs
        for filename in [v['key_filename'] for v in certs.values() if v['key_filename'] is not False]:
            shutil.copy(os.path.join(settings.FIXTURES_DIR, filename), self.options['CA_DIR'])

        self.mock = patch.object(ca_storage, 'location', self.options['CA_DIR'])
        self.mock_ = patch.object(ca_storage, '_location', self.options['CA_DIR'])
        self.mock.start()
        self.mock_.start()

        super(override_tmpcadir, self).enable()

    def disable(self):
        super(override_tmpcadir, self).disable()
        self.mock.stop()
        self.mock_.stop()
        shutil.rmtree(self.options['CA_DIR'])


class DjangoCATestCase(TestCase):
    """Base class for all testcases with some enhancements."""

    re_false_password = r'^(Bad decrypt\. Incorrect password\?|Could not deserialize key data\.)$'

    if six.PY2:  # pragma: no branch, pragma: only py2
        assertRaisesRegex = TestCase.assertRaisesRegexp

        @contextmanager
        def assertLogs(self, logger=None, level=None):
            """Simulate assertLogs() from Python3 using the textfixtures module.

            Note that this context manager only allows you to compare the ouput
            attribute, not the "records" attribute."""

            class Py2LogCapture(object):
                @property
                def output(self):
                    return ['%s:%s:%s' % (r[1], r[0], r[2]) for r in lc.actual()]

            with LogCapture() as lc:
                yield Py2LogCapture()

    @classmethod
    def setUpClass(cls):
        super(DjangoCATestCase, cls).setUpClass()

        if cls._overridden_settings:
            reload_module(ca_settings)

    @classmethod
    def tearDownClass(cls):
        overridden = False
        if hasattr(cls, '_cls_overridden_context'):
            overridden = True

        super(DjangoCATestCase, cls).tearDownClass()

        if overridden is True:
            reload_module(ca_settings)

    def settings(self, **kwargs):
        """Decorator to temporarily override settings."""
        return override_settings(**kwargs)

    def tmpcadir(self, **kwargs):
        """Context manager to use a temporary CA dir."""
        return override_tmpcadir(**kwargs)

    def mock_cadir(self, path):
        return mock_cadir(path)

    def assertAuthorityKeyIdentifier(self, issuer, cert, critical=False):
        self.assertEqual(cert.authority_key_identifier.value, issuer.subject_key_identifier.value)

    def assertBasic(self, cert, algo='SHA256'):
        """Assert some basic key properties."""
        self.assertEqual(cert.version, x509.Version.v3)
        self.assertIsInstance(cert.public_key(), rsa.RSAPublicKey)
        self.assertIsInstance(cert.signature_hash_algorithm, getattr(hashes, algo.upper()))

    def assertCRL(self, crl, certs=None, signer=None, expires=86400, algorithm=None, encoding=Encoding.PEM,
                  idp=None, extensions=None, crl_number=0):
        certs = certs or []
        signer = signer or self.ca
        algorithm = algorithm or ca_settings.CA_DIGEST_ALGORITHM
        extensions = extensions or []
        expires = datetime.utcnow() + timedelta(seconds=expires)

        if idp is not None:  # pragma: no branch, pragma: only cryptography>=2.5
            extensions.append(idp)
        extensions.append(x509.Extension(
            value=x509.CRLNumber(crl_number=crl_number),
            critical=False, oid=ExtensionOID.CRL_NUMBER
        ))
        extensions.append(signer.authority_key_identifier.as_extension())

        if encoding == Encoding.PEM:
            crl = x509.load_pem_x509_crl(crl, default_backend())
        else:
            crl = x509.load_der_x509_crl(crl, default_backend())

        self.assertIsInstance(crl.signature_hash_algorithm, type(algorithm))
        self.assertTrue(crl.is_signature_valid(signer.x509.public_key()))
        self.assertEqual(crl.issuer, signer.x509.subject)
        self.assertEqual(crl.last_update, datetime.utcnow())
        self.assertEqual(crl.next_update, expires)
        self.assertCountEqual(list(crl.extensions), extensions)

        entries = {e.serial_number: e for e in crl}
        expected = {c.x509.serial_number: c for c in certs}
        self.assertCountEqual(entries, expected)
        for serial, entry in entries.items():
            self.assertEqual(entry.revocation_date, datetime.utcnow())
            self.assertEqual(list(entry.extensions), [])

    @contextmanager
    def assertCommandError(self, msg):
        """Context manager asserting that CommandError is raised.

        Parameters
        ----------

        msg : str
            The regex matching the exception message.
        """
        with self.assertRaisesRegex(CommandError, msg):
            yield

    def assertHasExtension(self, cert, oid):
        """Assert that the given cert has the passed extension."""

        self.assertIn(oid, [e.oid for e in cert.x509.extensions])

    def assertHasNotExtension(self, cert, oid):
        """Assert that the given cert does *not* have the passed extension."""
        self.assertNotIn(oid, [e.oid for e in cert.x509.extensions])

    def assertIssuer(self, issuer, cert):
        self.assertEqual(cert.issuer, issuer.subject)

    def assertMessages(self, response, expected):
        messages = [str(m) for m in list(get_messages(response.wsgi_request))]
        self.assertEqual(messages, expected)

    def assertNotRevoked(self, cert):
        if isinstance(cert, CertificateAuthority):
            cert = CertificateAuthority.objects.get(serial=cert.serial)
        else:
            cert = Certificate.objects.get(serial=cert.serial)

        self.assertFalse(cert.revoked)
        self.assertIsNone(cert.revoked_reason)

    def assertParserError(self, args, expected, **kwargs):
        """Assert that given args throw a parser error."""

        kwargs.setdefault('script', os.path.basename(sys.argv[0]))
        expected = expected.format(**kwargs)

        buf = StringIO()
        with self.assertRaises(SystemExit), patch('sys.stderr', buf):
            self.parser.parse_args(args)

        output = buf.getvalue()
        self.assertEqual(output, expected)
        return output

    def assertPostCreateCa(self, post, ca):
        post.assert_called_once_with(ca=ca, signal=post_create_ca, sender=CertificateAuthority)

    def assertPostIssueCert(self, post, cert):
        post.assert_called_once_with(cert=cert, signal=post_issue_cert, sender=Certificate)

    def assertPostRevoke(self, post, cert):
        post.assert_called_once_with(cert=cert, signal=post_revoke_cert, sender=Certificate)

    def assertPrivateKey(self, ca, password=None):
        key = ca.key(password)
        self.assertIsNotNone(key)
        self.assertTrue(key.key_size > 0)

    def assertRevoked(self, cert, reason=None):
        if isinstance(cert, CertificateAuthority):
            cert = CertificateAuthority.objects.get(serial=cert.serial)
        else:
            cert = Certificate.objects.get(serial=cert.serial)

        self.assertTrue(cert.revoked)

        if reason is None:
            self.assertIsNone(cert.revoked_reason)
        else:
            self.assertEqual(cert.revoked_reason, reason)

    def assertSerial(self, serial):
        """Assert that the serial matches a basic regex pattern."""
        self.assertIsNotNone(re.match('^[0-9A-F:]*$', serial), serial)

    @contextmanager
    def assertSignal(self, signal):
        handler = Mock()
        signal.connect(handler)
        yield handler
        signal.disconnect(handler)

    def assertSignature(self, chain, cert):
        # see: http://stackoverflow.com/questions/30700348
        store = X509Store()

        # set the time of the OpenSSL context - freezegun doesn't work, because timestamp comes from OpenSSL
        now = datetime.utcnow()
        store.set_time(now)

        for elem in chain:
            ca = load_certificate(FILETYPE_PEM, elem.dump_certificate())
            store.add_cert(ca)

            # Verify that the CA itself is valid
            store_ctx = X509StoreContext(store, ca)
            self.assertIsNone(store_ctx.verify_certificate())

        cert = load_certificate(FILETYPE_PEM, cert.dump_certificate())
        store_ctx = X509StoreContext(store, cert)
        self.assertIsNone(store_ctx.verify_certificate())

    def assertSubject(self, cert, expected):
        if not isinstance(expected, Subject):
            expected = Subject(expected)
        self.assertEqual(Subject([(s.oid, s.value) for s in cert.subject]), expected)

    @contextmanager
    def assertValidationError(self, errors):
        with self.assertRaises(ValidationError) as cm:
            yield
        self.assertEqual(cm.exception.message_dict, errors)

    def cmd(self, *args, **kwargs):
        """Call to a manage.py command using call_command."""
        kwargs.setdefault('stdout', StringIO())
        kwargs.setdefault('stderr', StringIO())
        stdin = kwargs.pop('stdin', StringIO())

        with patch('sys.stdin', stdin):
            call_command(*args, **kwargs)
        return kwargs['stdout'].getvalue(), kwargs['stderr'].getvalue()

    def cmd_e2e(self, cmd, stdin=None, stdout=None, stderr=None):
        """Call a management command the way manage.py does.

        Unlike call_command, this method also tests the argparse configuration of the called command.
        """
        stdout = stdout or StringIO()
        stderr = stderr or StringIO()
        if stdin is None:
            stdin = StringIO()

        with patch('sys.stdin', stdin), patch('sys.stdout', stdout), patch('sys.stderr', stderr):
            util = ManagementUtility(['manage.py', ] + list(cmd))
            util.execute()

        return stdout.getvalue(), stderr.getvalue()

    def get_cert_context(self, name):
        # Get a dictionary suitable for testing output based on the dictionary in basic.certs
        ctx = {}
        for key, value in certs[name].items():
            if isinstance(value, tuple):
                crit, val = value
                ctx['%s_critical' % key] = crit

                if isinstance(val, list):
                    for i, val_i in enumerate(val):
                        ctx['%s_%s' % (key, i)] = val_i
                else:
                    ctx[key] = val
            elif key == 'precert_poison':
                # NOTE: We use two keys here because if we don't have PrecertPoison, the name of the
                #       extension is "Unknown OID", so the order is different.
                if ca_settings.CRYPTOGRAPHY_HAS_PRECERT_POISON:  # pragma: only cryptography>=2.4
                    ctx['precert_poison'] = '\nPrecertPoison (critical): Yes'
                    ctx['precert_poison_unknown'] = ''
                else:  # pragma: no cover
                    ctx['precert_poison'] = ''
                    oid = '<ObjectIdentifier(oid=1.3.6.1.4.1.11129.2.4.3, name=Unknown OID)>'
                    ctx['precert_poison_unknown'] = '\nUnknownOID (critical):\n    %s' % oid
            elif key == 'pathlen':
                ctx[key] = value
                ctx['%s_text' % key] = 'unlimited' if value is None else value
            elif isinstance(value, Extension):
                ctx[key] = value

                if isinstance(value, ListExtension):
                    for i, val in enumerate(value):
                        ctx['%s_%s' % (key, i)] = val

                else:
                    ctx['%s_text' % key] = value.as_text()

                if value.critical:
                    ctx['%s_critical' % key] = ' (critical)'
                else:
                    ctx['%s_critical' % key] = ''
            else:
                ctx[key] = value

        if certs[name].get('parent'):
            parent = certs[certs[name]['parent']]
            ctx['parent_name'] = parent['name']
            ctx['parent_serial'] = parent['serial']

        ctx['key_path'] = ca_storage.path(certs[name]['key'])
        return ctx

    def get_idp(self, full_name=None, indirect_crl=False, only_contains_attribute_certs=False,
                only_contains_ca_certs=False, only_contains_user_certs=False, only_some_reasons=None,
                relative_name=None):
        if not ca_settings.CRYPTOGRAPHY_HAS_IDP:  # pragma: only cryptography<2.5
            return
        else:  # pragma: only cryptography>=2.5
            return x509.Extension(
                oid=ExtensionOID.ISSUING_DISTRIBUTION_POINT,
                value=x509.IssuingDistributionPoint(
                    full_name=full_name,
                    indirect_crl=indirect_crl,
                    only_contains_attribute_certs=only_contains_attribute_certs,
                    only_contains_ca_certs=only_contains_ca_certs,
                    only_contains_user_certs=only_contains_user_certs,
                    only_some_reasons=only_some_reasons,
                    relative_name=relative_name
                ), critical=True)

    @classmethod
    def expires(cls, days):
        now = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return now + timedelta(days + 1)

    @classmethod
    def create_ca(cls, name, **kwargs):
        """Create a new CA.

        Sets sane defaults for all required kwargs, so you only have to pass the name.
        """

        kwargs.setdefault('key_size', settings.CA_MIN_KEY_SIZE)
        kwargs.setdefault('key_type', 'RSA')
        kwargs.setdefault('algorithm', hashes.SHA256())
        kwargs.setdefault('expires', datetime.now() + timedelta(days=3560))
        kwargs.setdefault('parent', None)
        kwargs.setdefault('subject', Subject('/CN=generated.example.com'))

        ca = CertificateAuthority.objects.init(name=name, **kwargs)
        return ca

    @classmethod
    def load_ca(cls, name, x509, enabled=True, parent=None, **kwargs):
        """Load a CA from one of the preloaded files."""
        path = '%s.key' % name
        ca = CertificateAuthority(name=name, private_key_path=path, enabled=enabled, parent=parent,
                                  **kwargs)
        ca.x509 = x509  # calculates serial etc
        ca.save()
        return ca

    @classmethod
    def create_csr(cls, subject):
        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=1024, backend=default_backend())
        builder = x509.CertificateSigningRequestBuilder()

        builder = builder.subject_name(x509_name(subject))
        builder = builder.add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        request = builder.sign(private_key, hashes.SHA256(), default_backend())

        return private_key, request

    @classmethod
    def create_cert(cls, ca, csr, subject, san=None, **kwargs):
        cert_kwargs = get_cert_profile_kwargs()
        cert_kwargs.update(kwargs)
        cert_kwargs['subject'] = Subject(subject)
        cert = Certificate.objects.init(
            ca=ca, csr=csr, algorithm=hashes.SHA256(), expires=cls.expires(720),
            subject_alternative_name=san, **cert_kwargs)
        cert.full_clean()
        return cert

    @classmethod
    def load_cert(cls, ca, x509, csr=''):
        cert = Certificate(ca=ca, csr=csr)
        cert.x509 = x509
        cert.save()
        return cert

    @classmethod
    def get_subject(cls, cert):
        return {OID_NAME_MAPPINGS[s.oid]: s.value for s in cert.subject}

    @classmethod
    def get_extensions(cls, cert):
        # TODO: use cert.get_extensions() as soon as everything is moved to the new framework
        c = Certificate()
        c.x509 = cert
        exts = [e.oid._name for e in cert.extensions]
        if 'cRLDistributionPoints' in exts:
            exts.remove('cRLDistributionPoints')
            exts.append('crlDistributionPoints')

        exts = {}
        for ext in c.get_extensions():
            if isinstance(ext, Extension):
                exts[ext.__class__.__name__] = ext

            # old extension framework
            else:
                name, value = ext
                exts[name] = value

        return exts


@override_settings(CA_MIN_KEY_SIZE=512)
class DjangoCAWithCATestCase(DjangoCATestCase):
    """A test class that already has a CA predefined."""

    def setUp(self):
        super(DjangoCAWithCATestCase, self).setUp()
        self.cas = {k: self.load_ca(name=v['name'], x509=v['pub']['parsed']) for k, v in certs.items()
                    if v.get('type') == 'ca'}
        self.usable_cas = {name: ca for name, ca in self.cas.items()
                           if certs[name]['key_filename'] is not False}


class DjangoCAWithCertTestCase(DjangoCAWithCATestCase):
    def setUp(self):
        super(DjangoCAWithCertTestCase, self).setUp()

        self.certs = {}
        for name, data in certs.items():
            ca = self.cas[data['ca']]
            self.certs[name] = self.load_cert(ca, x509=data['pub']['parsed'], csr=data['csr']['pem'])
