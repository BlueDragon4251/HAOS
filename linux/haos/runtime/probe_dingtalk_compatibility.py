#!/usr/bin/env python3
"""Targeted Tea-OpenAPI/Cryptography compatibility; disposable local keys only."""
import hashlib
import hmac
from importlib.metadata import version
import json
from pathlib import Path
import sys


def main():
    root = Path(sys.argv[1]).resolve()
    manifest = json.loads((root / 'runtime/source.json').read_text())
    expected = manifest['gateway_compatibility_versions']
    assert expected == {'alibabacloud-tea-openapi': '0.4.6'}
    assert {name: version(name) for name in expected} == expected
    assert version('cryptography') == '50.0.0'
    from alibabacloud_tea_openapi.utils import Utils, rsa_sign, signature_method
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    cases = []
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    message = b'disposable local DingTalk compatibility fixture'
    for label, secret in (
        ('pkcs8', pem), ('bare_pkcs8', b''.join(pem.splitlines()[1:-1])),
        ('sdk_mislabeled_pkcs8', pem.replace(b'PRIVATE KEY', b'RSA PRIVATE KEY')),
    ):
        signed = rsa_sign(message, secret)
        key.public_key().verify(signed, message, padding.PKCS1v15(), hashes.SHA256())
        try:
            key.public_key().verify(signed, message + b' changed', padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature:
            pass
        else:
            raise AssertionError('tampered signature accepted')
        cases.append('actual_tea_rsa_sign_cryptography50_' + label)
    signed = signature_method(pem.decode(), message.decode(), 'ACS3-RSA-SHA256')
    key.public_key().verify(signed, message, padding.PKCS1v15(), hashes.SHA256())
    cases.append('actual_tea_signature_dispatch_RSA_SHA256')
    assert signature_method('fixture-secret', message.decode(), 'ACS3-HMAC-SHA256') == hmac.new(
        b'fixture-secret', message, hashlib.sha256).digest()
    cases.append('actual_tea_signature_dispatch_HMAC_SHA256')
    for header, expected_wait in ((None, None), ('', None), ('invalid', None), ('0', None),
                                   ('-1', None), ('1', 1), ('300', 300)):
        headers = {} if header is None else {'x-acs-retry-after': header}
        assert Utils.get_throttling_time_left(headers) == expected_wait
        cases.append('actual_tea_reviewed_retry_header_' + str(header))
    result = {'hermes_commit': manifest['upstream_commit'], 'versions': {
        **expected, 'cryptography': version('cryptography')}, 'cases': cases,
        'scope': 'Local SDK compatibility only; no live app, delivery or authorization acceptance.'}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
