"""Disposable loopback CA/leaf for actual webhook TLS fixtures; never production trust."""
from datetime import datetime,timezone,timedelta
from pathlib import Path


def create(root,hostname):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
    root=Path(root);now=datetime.now(timezone.utc)
    ca_key=ec.generate_private_key(ec.SECP256R1());ca_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'HAOS disposable webhook fixture')])
    ca=(x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True,path_length=0),True)
        .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),False).sign(ca_key,hashes.SHA256()))
    key=ec.generate_private_key(ec.SECP256R1())
    leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,hostname)]))
        .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False,path_length=None),True)
        .add_extension(x509.KeyUsage(True,False,False,False,False,False,False,False,False),True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname),x509.DNSName('localhost')]),False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),False).sign(ca_key,hashes.SHA256()))
    cert=leaf.public_bytes(serialization.Encoding.PEM).decode();private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    (root/'ca.pem').write_bytes(ca.public_bytes(serialization.Encoding.PEM));(root/'certificate.pem').write_text(cert)
    (root/'key.pem').write_text(private);(root/'key.pem').chmod(0o600)
    return {'public_url':'https://'+hostname+'/webhooks/twilio','certificate':cert,'private_key':private,'bind_host':'127.0.0.1','public_listener':False}
