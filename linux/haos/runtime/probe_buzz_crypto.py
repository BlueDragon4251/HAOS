#!/usr/bin/env python3
"""Cross-check actual pinned Hermes Nostr signing with the official Rust SDK."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from plugins.platforms.buzz import nostr_auth
    verifier=Path(sys.argv[2]).resolve(strict=True);cases=[]
    def verify(raw,valid):
        result=subprocess.run([str(verifier)],input=raw,capture_output=True,timeout=5)
        value=json.loads(result.stdout)
        assert len(result.stdout)<=256 and result.stderr==b''
        assert (result.returncode==0)==valid and value.get('valid') is valid
        return value
    # Public deterministic local fixture scalar, never an account credential.
    scalar=format(1,'064x')
    auth=nostr_auth.build_auth_event(private_key=scalar,challenge='fixed-local-NIP42-challenge',
        relay_url='wss://buzz.fixture.invalid',created_at=1793332800,auxiliary_randomness=bytes(32))
    checked=verify(json.dumps(auth,separators=(',',':')).encode(),True)
    assert checked=={'valid':True,'id':auth['id'],'pubkey':auth['pubkey']}
    cases.append('actual_frozen_Hermes_NIP42_BIP340_auth_signature_and_event_identity_verified_by_official_nostr_0447_SDK')
    event={'pubkey':auth['pubkey'],'created_at':1793332801,'kind':9,
        'tags':[['h','01234567-89ab-4cde-8012-3456789abcde'],['p','2'*64]],'content':'Signed local text: ä / 🙂\nsecond line'}
    raw=json.dumps([0,event['pubkey'],event['created_at'],event['kind'],event['tags'],event['content']],ensure_ascii=False,separators=(',',':')).encode()
    event['id']=hashlib.sha256(raw).hexdigest();event['sig']=nostr_auth.schnorr_sign(bytes.fromhex(event['id']),scalar,auxiliary_randomness=bytes(32)).hex()
    checked=verify(json.dumps(event,ensure_ascii=False,separators=(',',':')).encode(),True)
    assert checked['id']==event['id'] and checked['pubkey']==auth['pubkey']
    cases.append('actual_native_Schnorr_signing_and_official_Rust_event_verification_agree_on_complete_UTF8_channel_message_and_tags')
    changes=[{'content':'tampered source'},{'tags':[['h','11234567-89ab-4cde-8012-3456789abcde']]},
        {'pubkey':'f'*64},{'id':'0'*64},{'sig':'f'*128},{'created_at':event['created_at']+1},{'sig':event['sig'][:-2]+'ff'}]
    for index,change in enumerate(changes):
        verify(json.dumps({**event,**change},separators=(',',':')).encode(),False)
        cases.append('actual_official_SDK_rejects_tampered_digest_signature_or_signed_source_field_'+str(index))
    for raw in [b'{}',b'[]',b'not-json',b'x'*1048577]:
        verify(raw,False)
    cases.append('fixed_offline_verifier_rejects_malformed_and_oversized_input_without_echoing_signed_content_or_parser_errors')
    receipt={'passed':len(cases),'cases':cases,'pinned_hermes':'f97608f178d1ffeca59860195ab7da295f7c8e5f',
        'official_nostr_SDK':'0.44.7','verifier_sha256':hashlib.sha256(verifier.read_bytes()).hexdigest(),
        'scope':'actual frozen Hermes signing code and compiled official Rust SDK; deterministic public local fixtures only',
        'actual_UID_relay_TLS_ingress_mission_delivery_GUI_or_public_activation':False}
    Path(sys.argv[3]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'passed':len(cases),'public_gateway':False}))


if __name__=='__main__':main()
