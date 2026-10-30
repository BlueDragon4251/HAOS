#!/usr/bin/env python3
"""Actual Google SDK RSA/JWT checks with explicit local certificate fixture."""
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from google.auth import crypt,jwt
    from haos.gateway_google_chat_auth import TokenVerifier,CERTS,CertificateRequest
    from haos.gateway_google_chat_admission import Refused
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'local-google-token-fixture')])
    now=datetime.now(timezone.utc)
    cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1)).sign(key,hashes.SHA256())
    private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    signer=crypt.RSASigner.from_string(private,key_id='local-fixture');calls=[];checks=[]
    def request(url,method='GET',**kwargs):
        assert url==CERTS and method=='GET' and not kwargs;calls.append(url)
        return SimpleNamespace(status=200,data=json.dumps({'local-fixture':cert.public_bytes(serialization.Encoding.PEM).decode()}).encode())
    audience='https://haos.fixture.invalid/google-chat';email='chat-caller@haos-fixture.iam.gserviceaccount.com'
    claims={'iss':'https://accounts.google.com','aud':audience,'sub':'123456789','email':email,'email_verified':True,'iat':int(time.time()),'exp':int(time.time())+3600}
    verifier=TokenVerifier(audience,email,lambda:checks.append(True),certificate_request=request)
    def token(change=None):return jwt.encode(signer,{**claims,**(change or {})}).decode()
    value=verifier.verify([('Authorization','Bearer '+token())]);assert set(value)=={'caller_sha256','token_sha256','authenticated_at'} and len(checks)==2 and len(calls)==1
    cases=['actual_Google_SDK_verifies_RSA_signature_official_issuer_exact_audience_verified_caller_and_expiry_with_no_token_return']
    for change in [{'aud':'https://other.invalid/google-chat'},{'iss':'https://other.invalid'},
        {'email':'different@haos-fixture.iam.gserviceaccount.com'},{'email_verified':False},
        {'iat':int(time.time())-7200,'exp':int(time.time())-3600},
        {'iat':int(time.time())+3600,'exp':int(time.time())+7200},{'exp':int(time.time())+14400}]:
        try:verifier.verify([('Authorization','Bearer '+token(change))])
        except Refused as error:assert error.reason=='invalid-authentication'
        else:raise AssertionError('invalid Google caller accepted')
        cases.append('actual_Google_SDK_or_additional_exact_caller_gate_refuses_'+next(iter(change)))
    signed=token();parts=signed.split('.');parts[2]=('A' if parts[2][0]!='A' else 'B')+parts[2][1:]
    for headers in [[('Authorization','Bearer '+'.'.join(parts))],[('Authorization','Bearer '+signed),('authorization','Bearer '+signed)],
        [('Authorization','Basic '+signed)],[],[('Authorization','Bearer '+signed+'\r\nextra')]]:
        try:verifier.verify(headers)
        except Refused:pass
        else:raise AssertionError('signature/header ambiguity accepted')
    cases.append('actual_signature_tampering_duplicate_authorization_wrong_scheme_missing_and_injected_headers_refused')
    transport=CertificateRequest(lambda:None)
    for url,kwargs in [('https://other.invalid',{}),(CERTS,{'method':'POST'}),(CERTS,{'headers':{'Authorization':'foreign'}})]:
        try:transport(url,**kwargs)
        except Refused:pass
        else:raise AssertionError('arbitrary certificate transport request accepted')
    cases.append('bounded_certificate_transport_refuses_foreign_URL_method_and_ambient_authorization_before_network')
    def revoked():raise PermissionError('withdrawn')
    verifier.current=revoked
    try:verifier.verify([('Authorization','Bearer '+signed)])
    except PermissionError:pass
    else:raise AssertionError('revoked callback authority accepted')
    cases.append('current_private_authority_is_required_before_any_certificate_or_token_work')
    receipt={'passed':len(cases),'cases':cases,'actual_Google_RSA_JWT_verification':True,
        'certificate_endpoint_is_explicit_local_fixture':True,'ephemeral_local_key_only':True,
        'live_Google_token_HTTP_listener_PubSub_UID_mission_GUI_or_public_activation':False}
    Path(sys.argv[1]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'passed':len(cases)}))


if __name__=='__main__':main()
