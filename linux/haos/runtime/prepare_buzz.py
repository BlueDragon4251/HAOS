#!/usr/bin/env python3
"""Validate exact official CLI inputs and restrict its default HTTP redirect policy."""
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib


def prepare(source,overlay):
    value=json.loads((overlay/'buzz-source.json').read_text())
    client=source/'crates/buzz-cli/src/client.rs';messages=source/'crates/buzz-cli/src/commands/messages.rs'
    lock=source/'Cargo.lock';helper=overlay/'buzz-verify/Cargo.lock';validation=source/'crates/buzz-media/src/validation.rs'
    for path,expected in [(client,value['client_original_sha256']),(messages,value['messages_original_sha256']),(lock,value['official_lock_sha256']),
            (helper,value['helper_lock_sha256']),(validation,value['media_validation_original_sha256'])]:
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
    response_start=patched.index('    async fn handle_response(&self, resp: reqwest::Response) -> Result<String, CliError> {')
    response_end=patched.index('\n    }\n}',response_start)+len('\n    }')
    response=patched[response_start:response_end]
    body_anchor='''        if !resp.status().is_success() {
            let status = resp.status().as_u16();
            let body = resp.text().await.unwrap_or_default();'''
    if response.count(body_anchor)!=1 or response.count('Ok(resp.text().await?)')!=1:
        raise ValueError('pinned Buzz HTTP response body handler changed')
    body_patch='''        let status = resp.status();
        if status.as_u16() == 401 || status.as_u16() == 403 {
            return Err(CliError::Relay { status: status.as_u16(), body: "authentication refused".into() });
        }
        let limit: usize = if status.is_success() { 8 * 1024 * 1024 } else { 65536 };
        let overflow = || {
            if status.is_success() {
                CliError::Other("response_limit".into())
            } else {
                CliError::Relay { status: status.as_u16(), body: "response_limit".into() }
            }
        };
        if resp.content_length().map(|length| length > limit as u64).unwrap_or(false) {
            return Err(overflow());
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = resp.chunk().await? {
            if chunk.len() > limit - bytes.len() {
                return Err(overflow());
            }
            bytes.extend_from_slice(&chunk);
        }
        let body = String::from_utf8(bytes).map_err(|_| {
            if status.is_success() { CliError::Other("invalid response encoding".into()) }
            else { CliError::Relay { status: status.as_u16(), body: "invalid response encoding".into() } }
        })?;
        if !status.is_success() {
            let status = status.as_u16();'''
    response=response.replace('(&self, resp: reqwest::Response)','(&self, mut resp: reqwest::Response)')
    response=response.replace(body_anchor,body_patch).replace('Ok(resp.text().await?)','Ok(body)')
    patched=patched[:response_start]+response+patched[response_end:]
    media_start=patched.index('    pub async fn download_media(&self, input: &str) -> Result<bytes::Bytes, CliError> {')
    media_end=patched.index('\n    }\n',media_start)+len('\n    }')
    media=patched[media_start:media_end]
    media_anchor='''                if !resp.status().is_success() {
                    let status = resp.status().as_u16();
                    let body = resp.text().await.unwrap_or_default();
                    return Err(CliError::Relay { status, body });
                }
                resp.bytes().await.map_err(CliError::Network)'''
    if (media.count(media_anchor)!=1 or media.count('.timeout(Duration::from_secs(120))')!=1
            or media.count('let resp = self')!=1):raise ValueError('pinned Buzz private media GET changed')
    media=media.replace('let resp = self','let mut resp = self').replace('.timeout(Duration::from_secs(120))',
        '.timeout(env_duration_secs("BUZZ_TIMEOUT_SECS", 30))\n            .connect_timeout(env_duration_secs("BUZZ_CONNECT_TIMEOUT_SECS", 15))')
    media_patch='''                if !resp.status().is_success() {
                    self.handle_response(resp).await?;
                    return Err(CliError::Other("invalid media response status".into()));
                }
                let limit: usize = 8 * 1024 * 1024;
                if resp.content_length().map(|length| length > limit as u64).unwrap_or(false) {
                    return Err(CliError::Other("media_response_limit".into()));
                }
                let mut data = Vec::new();
                while let Some(chunk) = resp.chunk().await? {
                    if chunk.len() > limit - data.len() {
                        return Err(CliError::Other("media_response_limit".into()));
                    }
                    data.extend_from_slice(&chunk);
                }
                Ok(bytes::Bytes::from(data))'''
    media=media.replace(media_anchor,media_patch)
    patched=patched[:media_start]+media+patched[media_end:]
    upload_start=patched.index('    pub async fn upload_file(&self, file_path: &str) -> Result<BlobDescriptor, CliError> {')
    upload_end=patched.index('\n    }\n',upload_start)+len('\n    }')
    upload=patched[upload_start:upload_end]
    source_validation=validation.read_text()
    generic=source_validation[source_validation.index('fn file_mime_to_ext('):source_validation.index('\n/// Validate uploaded bytes for the **generic file** upload path.')]
    mimes=sorted({'application/octet-stream',*re.findall(r'"([a-z0-9.+-]+/[a-z0-9.+-]+)"',generic)})
    deny=source_validation[source_validation.index('const BLOCKED_FILE_MIME_TYPES:'):source_validation.index('\n/// Map a sniffed MIME type')]
    if set(mimes)&set(re.findall(r'"([a-z0-9.+-]+/[a-z0-9.+-]+)"',deny)):
        raise ValueError('generic CLI MIME subset intersects the exact relay deny policy')
    mime_anchor='        if !ALLOWED_MIMES.contains(&mime.as_str()) {'
    read_anchor='        let bytes = std::fs::read(file_path)'
    timeout_anchor='''        let upload_timeout = if mime.starts_with("video/") {
            Duration::from_secs(600)
        } else {
            Duration::from_secs(120)
        };'''
    response_primary='''                    let status = resp.status();
                    if !status.is_success() {
                        let s = status.as_u16();
                        let body = resp.text().await.unwrap_or_default();
                        return Err(CliError::Relay { status: s, body });
                    }
                    resp.json::<BlobDescriptor>().await.map_err(CliError::from)'''
    response_legacy='''                if !resp.status().is_success() {
                    let status = resp.status().as_u16();
                    let body = resp.text().await.unwrap_or_default();
                    return Err(CliError::Relay { status, body });
                }
                resp.json::<BlobDescriptor>().await.map_err(CliError::from)'''
    for expected in [mime_anchor,read_anchor,timeout_anchor,response_primary,response_legacy]:
        if upload.count(expected)!=1:raise ValueError('pinned Buzz immutable upload or descriptor handling changed')
    upload=upload.replace(read_anchor,'''        if metadata.len() == 0 || metadata.len() > 8 * 1024 * 1024 {
            return Err(CliError::Usage("private upload exceeds bounded nonempty file size".into()));
        }
''' + read_anchor)
    generic_list=', '.join(json.dumps(mime) for mime in mimes)
    upload=upload.replace(mime_anchor,'        let generic: &[&str] = &['+generic_list+'];\n'
        '        let generic_enabled = matches!(std::env::var("HAOS_BUZZ_GENERIC_FILES").as_deref(), Ok("1"));\n'
        '        if !ALLOWED_MIMES.contains(&mime.as_str()) && !(generic_enabled && generic.contains(&mime.as_str())) {')
    upload=upload.replace(timeout_anchor,'        let upload_timeout = env_duration_secs("BUZZ_TIMEOUT_SECS", 30);')
    upload=upload.replace(response_primary,'''                    let body = self.handle_response(resp).await?;
                    serde_json::from_str::<BlobDescriptor>(&body)
                        .map_err(|_| CliError::Other("invalid upload descriptor".into()))''')
    upload=upload.replace(response_legacy,'''                let body = self.handle_response(resp).await?;
                serde_json::from_str::<BlobDescriptor>(&body)
                    .map_err(|_| CliError::Other("invalid upload descriptor".into()))''')
    patched=patched[:upload_start]+upload+patched[upload_end:]
    query=messages.read_text();query_anchor='    if let Some(s) = since {\n        filter["since"] = serde_json::json!(s);\n    }\n\n    let resp = client.query(&filter).await?;'
    if query.count(query_anchor)!=1:raise ValueError('pinned Buzz message query cursor changed')
    query_patch=query_anchor.replace('    let resp = client.query(&filter).await?;', '    // HAOS private history supplies the relay\'s existing composite cursor.\n    // It is read-only, scoped to this process and still uses the exact channel.\n    if let Ok(before_id) = std::env::var("HAOS_BUZZ_BEFORE_ID") {\n        validate_hex64(&before_id)?;\n        if before.is_none() {\n            return Err(CliError::Usage("composite history cursor requires its exact timestamp".into()));\n        }\n        filter["before_id"] = serde_json::json!(before_id);\n    }\n    let resp = client.query(&filter).await?;')
    prepared_query=query.replace(query_anchor,query_patch)
    parse_anchor='''    let resp = client.query(&filter).await?;
    let mut events: Vec<serde_json::Value> = serde_json::from_str(&resp).unwrap_or_default();
    events.sort_by_key(|e| e.get("created_at").and_then(|v| v.as_u64()).unwrap_or(0));'''
    # Restrict this change to get-messages, not search/thread/write behavior.
    start=prepared_query.index('pub async fn cmd_get_messages(')
    end=prepared_query.index('\npub fn resolve_thread_target(',start)
    segment=prepared_query[start:end]
    if segment.count(parse_anchor)!=1:raise ValueError('pinned Buzz history response parser changed')
    segment=segment.replace(parse_anchor,parse_anchor.replace('serde_json::from_str(&resp).unwrap_or_default()',
        'serde_json::from_str(&resp).map_err(|_| CliError::Other("invalid history response".into()))?'))
    prepared_query=prepared_query[:start]+segment+prepared_query[end:]
    send_anchor='''    let event = client.sign_event(builder)?;
    let emitted_mentions = event_mention_pubkeys(&event);
    let resp = client.submit_event(event).await?;'''
    if prepared_query.count(send_anchor)!=1:raise ValueError('pinned Buzz signed message publication changed')
    send_patch='''    let event = client.sign_event(builder)?;
    // HAOS owns the private per-operation approval socket. Preserve the real
    // native builder/signature; never publish before durable custody and ACK.
    if let Some(name) = std::env::var_os("HAOS_BUZZ_APPROVAL_SOCKET") {
        use std::io::{Read, Write};
        use std::os::linux::net::SocketAddrExt;
        use std::os::unix::net::{SocketAddr, UnixStream};
        let refused = || CliError::Other("private event approval refused".into());
        let name = name.to_str().ok_or_else(refused)?;
        let nonce = name.strip_prefix("haos-buzz-").ok_or_else(refused)?;
        if nonce.len() != 64 || !nonce.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
            return Err(refused());
        }
        let address = SocketAddr::from_abstract_name(name.as_bytes()).map_err(|_| refused())?;
        let mut channel = UnixStream::connect_addr(&address).map_err(|_| refused())?;
        let deadline = Some(std::time::Duration::from_secs(10));
        channel.set_read_timeout(deadline).map_err(|_| refused())?;
        channel.set_write_timeout(deadline).map_err(|_| refused())?;
        let original = serde_json::to_vec(&event).map_err(|_| refused())?;
        if original.is_empty() || original.len() > 1048576 { return Err(refused()); }
        channel.write_all(&(original.len() as u32).to_be_bytes()).map_err(|_| refused())?;
        channel.write_all(&original).map_err(|_| refused())?;
        let mut approval = [0u8; 1];
        channel.read_exact(&mut approval).map_err(|_| refused())?;
        if approval != [1] { return Err(refused()); }
    }
    let emitted_mentions = event_mention_pubkeys(&event);
    let resp = client.submit_event(event).await?;'''
    replay='''    let event = if let Some(fd) = std::env::var_os("HAOS_BUZZ_REPLAY_FD") {
        use std::io::Read;
        let refused = || CliError::Other("private signed replay refused".into());
        let fd = fd.to_str().ok_or_else(refused)?;
        if fd.is_empty() || fd.len() > 10 || !fd.bytes().all(|b| b.is_ascii_digit()) {
            return Err(refused());
        }
        let descriptor: u32 = fd.parse().map_err(|_| refused())?;
        if descriptor < 3 || descriptor > i32::MAX as u32 { return Err(refused()); }
        let stream = std::fs::File::open(format!("/proc/self/fd/{descriptor}")).map_err(|_| refused())?;
        let mut raw = Vec::new();
        stream.take(1048577).read_to_end(&mut raw).map_err(|_| refused())?;
        if raw.is_empty() || raw.len() > 1048576 { return Err(refused()); }
        let replay: nostr::Event = serde_json::from_slice(&raw).map_err(|_| refused())?;
        replay.verify().map_err(|_| refused())?;
        if replay.pubkey != client.keys().public_key() { return Err(refused()); }
        replay
    } else {
        client.sign_event(builder)?
    };'''
    send_patch=send_patch.replace('    let event = client.sign_event(builder)?;',replay)
    prepared_query=prepared_query.replace(send_anchor,send_patch)
    file_start=prepared_query.index('    // Upload files and build imeta tags\n')
    file_end=prepared_query.index('    let final_content = if media_content.is_empty() {',file_start)
    files=prepared_query[file_start:file_end]
    if (files.count('let desc = client')!=1 or files.count('upload_file(file_path)')!=1
            or files.count('media_tags.push(crate::client::build_imeta_tag(&desc));')!=1):
        raise ValueError('pinned Buzz native message attachment builder changed')
    prepared_query=prepared_query[:file_start]+'''    // Preserve the actual imeta codec for root-sealed, already uploaded files.
    fn append_private_descriptor(
        desc: &crate::client::BlobDescriptor, name: &str,
        tags: &mut Vec<Vec<String>>, content: &mut String,
    ) -> Result<(), CliError> {
        if name.is_empty() || name.len() > 120
            || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
            || name.starts_with('.') || desc.size == 0 || desc.size > 8 * 1024 * 1024 {
            return Err(CliError::Usage("invalid private uploaded file descriptor".into()));
        }
        let mut tag = crate::client::build_imeta_tag(desc);
        tag.push(format!("filename {name}"));
        tags.push(tag);
        if desc.mime_type.starts_with("video/") {
            content.push_str("\\n![video](");
        } else if desc.mime_type.starts_with("image/") {
            content.push_str("\\n![image](");
        } else {
            content.push_str(&format!("\\n[{name}]("));
        }
        content.push_str(&desc.url);
        content.push(')');
        Ok(())
    }
    let mut media_tags: Vec<Vec<String>> = Vec::new();
    let mut media_content = String::new();
    if let Some(fd) = std::env::var_os("HAOS_BUZZ_UPLOADED_FD") {
        use std::io::Read;
        #[derive(serde::Deserialize)]
        #[serde(deny_unknown_fields)]
        struct PrivateFile { descriptor: crate::client::BlobDescriptor, name: String }
        let refused = || CliError::Other("private uploaded manifest refused".into());
        if !p.files.is_empty() { return Err(refused()); }
        let fd = fd.to_str().ok_or_else(refused)?;
        if fd.is_empty() || fd.len() > 10 || !fd.bytes().all(|b| b.is_ascii_digit()) { return Err(refused()); }
        let descriptor: u32 = fd.parse().map_err(|_| refused())?;
        if descriptor < 3 || descriptor > i32::MAX as u32 { return Err(refused()); }
        let stream = std::fs::File::open(format!("/proc/self/fd/{descriptor}")).map_err(|_| refused())?;
        let mut raw = Vec::new();
        stream.take(65537).read_to_end(&mut raw).map_err(|_| refused())?;
        if raw.is_empty() || raw.len() > 65536 { return Err(refused()); }
        let files: Vec<PrivateFile> = serde_json::from_slice(&raw).map_err(|_| refused())?;
        if files.is_empty() || files.len() > 4 { return Err(refused()); }
        for file in files {
            append_private_descriptor(&file.descriptor, &file.name, &mut media_tags, &mut media_content)?;
        }
    }
    for file_path in &p.files {
        let desc = client.upload_file(file_path).await
            .map_err(|e| CliError::Other(format!("upload failed: {e}")))?;
        let name = std::path::Path::new(file_path).file_name().and_then(|name| name.to_str())
            .ok_or_else(|| CliError::Usage("bounded upload filename required".into()))?;
        append_private_descriptor(&desc, name, &mut media_tags, &mut media_content)?;
    }
''' + prepared_query[file_end:]
    client.write_text(patched);messages.write_text(prepared_query)
    return {**value,'generic_file_mime_types':mimes,'client_prepared_sha256':hashlib.sha256(patched.encode()).hexdigest(),
        'messages_prepared_sha256':hashlib.sha256(prepared_query.encode()).hexdigest()}


if __name__=='__main__':
    print(json.dumps(prepare(Path(sys.argv[1]),Path(sys.argv[2])),indent=2))
