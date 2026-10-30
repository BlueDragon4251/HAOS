"""Owner-provided verified HTTPS material for the fixed LINE webhook endpoint."""
from datetime import datetime,timezone
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import ssl
import stat
import tempfile
from urllib.parse import urlsplit


def material(value,*,verify=True,webhook_path='/line/webhook'):
    if webhook_path not in {'/line/webhook','/webhooks/twilio','/feishu/webhook','/a2a','/google-chat'}:raise ValueError('reviewed webhook TLS path required')
    required={'public_url','certificate','private_key','bind_host','public_listener'}
    if not isinstance(value,dict) or set(value)!=required:raise ValueError('exact LINE HTTPS material and listener consent required')
    if (not isinstance(value['bind_host'],str) or value['bind_host'] not in {'127.0.0.1','0.0.0.0','::'} or type(value['public_listener']) is not bool
            or value['public_listener']!=(value['bind_host']!='127.0.0.1')):
        raise ValueError('explicit owner approval required for a public LINE listener')
    try:
        address=urlsplit(value['public_url']);host=address.hostname
        if (address.scheme!='https' or not host or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?',host)
                or '.' not in host or host.endswith('.') or address.username or address.password
                or address.port not in {None,443} or address.path!=webhook_path or address.query or address.fragment):raise ValueError
        try:ipaddress.ip_address(host)
        except ValueError:pass
        else:raise ValueError
        for field,limit in [('certificate',16384),('private_key',8192)]:
            if not isinstance(value[field],str) or not 1<=len(value[field].encode('ascii'))<=limit:raise ValueError
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa,ec,ed25519,ed448
        from cryptography.x509.verification import PolicyBuilder,Store
        chain=x509.load_pem_x509_certificates(value['certificate'].encode('ascii'))
        if not 1<=len(chain)<=8:raise ValueError
        key=serialization.load_pem_private_key(value['private_key'].encode('ascii'),password=None)
        if not (isinstance(key,rsa.RSAPrivateKey) and key.key_size>=2048
                or isinstance(key,ec.EllipticCurvePrivateKey) and key.key_size>=256
                or isinstance(key,(ed25519.Ed25519PrivateKey,ed448.Ed448PrivateKey))):raise ValueError
        encode=lambda public:public.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        if encode(key.public_key())!=encode(chain[0].public_key()):raise ValueError
        if verify:
            roots=[x509.load_der_x509_certificate(raw) for raw in ssl.create_default_context().get_ca_certs(binary_form=True)]
            verifier=PolicyBuilder().store(Store(roots)).time(datetime.now(timezone.utc)).build_server_verifier(x509.DNSName(host))
            verifier.verify(chain[0],chain[1:])
        certificate=''.join(cert.public_bytes(serialization.Encoding.PEM).decode('ascii') for cert in chain)
        private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode('ascii')
    except Exception:
        raise ValueError('LINE HTTPS certificate must be locally trusted, current, match the public hostname and private key') from None
    return {'public_url':'https://'+host+webhook_path,'certificate':certificate,'private_key':private,
        'bind_host':value['bind_host'],'public_listener':value['public_listener']}


def _private(path):
    own=path.lstat()
    if (path.resolve()!=path or not stat.S_ISDIR(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077):
        raise PermissionError('private service-owned TLS directory required')


def _retain(directory,name,data):
    target=directory/name
    def existing():
        fd=os.open(target,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as source:
            own=os.fstat(source.fileno())
            if (not stat.S_ISREG(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077
                    or own.st_nlink!=1 or source.read(len(data)+1)!=data):
                raise PermissionError('existing private LINE TLS material differs; owner recovery required')
    if target.exists() or target.is_symlink():existing();return target
    descriptor,temporary=tempfile.mkstemp(prefix='.line-tls-',dir=directory)
    try:
        with os.fdopen(descriptor,'wb') as output:output.write(data);output.flush();os.fsync(output.fileno())
        try:os.link(temporary,target)
        except FileExistsError:existing()
    finally:os.unlink(temporary)
    descriptor=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return target


def context(value,profile,*,webhook_path='/line/webhook'):
    value=material(value,webhook_path=webhook_path);profile=Path(profile);_private(profile)
    directory=profile/'tls'
    try:directory.mkdir(mode=0o700)
    except FileExistsError:pass
    _private(directory)
    fingerprint=hashlib.sha256(value['certificate'].encode()).hexdigest()
    certificate=_retain(directory,fingerprint+'.chain.pem',value['certificate'].encode())
    private=_retain(directory,fingerprint+'.key.pem',value['private_key'].encode())
    result=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);result.minimum_version=ssl.TLSVersion.TLSv1_2
    result.load_cert_chain(certificate,private)
    return result
