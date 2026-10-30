#!/usr/bin/env python3
"""Validate exact official CLI inputs and restrict its default HTTP redirect policy."""
import hashlib
import json
from pathlib import Path
import sys
import tomllib


def prepare(source,overlay):
    value=json.loads((overlay/'buzz-source.json').read_text())
    client=source/'crates/buzz-cli/src/client.rs';lock=source/'Cargo.lock';helper=overlay/'buzz-verify/Cargo.lock'
    for path,expected in [(client,value['client_original_sha256']),(lock,value['official_lock_sha256']),
            (helper,value['helper_lock_sha256'])]:
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('Buzz build input differs from the reviewed exact source')
    allowed={(row['name'],row['version'],row.get('source'),row.get('checksum')) for row in tomllib.loads(lock.read_text())['package']}
    for row in tomllib.loads(helper.read_text())['package']:
        if row['name']=='haos-buzz-verify':continue
        if (row['name'],row['version'],row.get('source'),row.get('checksum')) not in allowed:
            raise ValueError('offline verifier dependency does not match the exact official CLI SDK lock')
    text=client.read_text();anchor='''        let http = reqwest::Client::builder()
            .timeout(env_duration_secs("BUZZ_TIMEOUT_SECS", 30))'''
    if text.count(anchor)!=1:raise ValueError('pinned Buzz default HTTP constructor changed')
    # Preserve actual native NIP-98 signing, body creation and idempotent event
    # handling. Only disable redirects from the exact owner-approved origin.
    patched=text.replace(anchor,'''        let http = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(env_duration_secs("BUZZ_TIMEOUT_SECS", 30))''')
    client.write_text(patched)
    return {**value,'client_prepared_sha256':hashlib.sha256(patched.encode()).hexdigest()}


if __name__=='__main__':
    print(json.dumps(prepare(Path(sys.argv[1]),Path(sys.argv[2])),indent=2))
