#!/usr/bin/env python3
"""Validate exact official CLI inputs and restrict its default HTTP redirect policy."""
import hashlib
import json
from pathlib import Path
import sys
import tomllib


def prepare(source,overlay):
    value=json.loads((overlay/'buzz-source.json').read_text())
    client=source/'crates/buzz-cli/src/client.rs';messages=source/'crates/buzz-cli/src/commands/messages.rs'
    lock=source/'Cargo.lock';helper=overlay/'buzz-verify/Cargo.lock'
    for path,expected in [(client,value['client_original_sha256']),(messages,value['messages_original_sha256']),(lock,value['official_lock_sha256']),
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
    query=messages.read_text();query_anchor='    if let Some(s) = since {\n        filter["since"] = serde_json::json!(s);\n    }\n\n    let resp = client.query(&filter).await?;'
    if query.count(query_anchor)!=1:raise ValueError('pinned Buzz message query cursor changed')
    query_patch=query_anchor.replace('    let resp = client.query(&filter).await?;', '    // HAOS private history supplies the relay\'s existing composite cursor.\n    // It is read-only, scoped to this process and still uses the exact channel.\n    if let Ok(before_id) = std::env::var("HAOS_BUZZ_BEFORE_ID") {\n        validate_hex64(&before_id)?;\n        if before.is_none() {\n            return Err(CliError::Usage("composite history cursor requires its exact timestamp".into()));\n        }\n        filter["before_id"] = serde_json::json!(before_id);\n    }\n    let resp = client.query(&filter).await?;')
    prepared_query=query.replace(query_anchor,query_patch)
    client.write_text(patched);messages.write_text(prepared_query)
    return {**value,'client_prepared_sha256':hashlib.sha256(patched.encode()).hexdigest(),
        'messages_prepared_sha256':hashlib.sha256(prepared_query.encode()).hexdigest()}


if __name__=='__main__':
    print(json.dumps(prepare(Path(sys.argv[1]),Path(sys.argv[2])),indent=2))
