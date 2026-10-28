"""Bounded MIME inspection and private execution of the pinned attachment codec."""
from email import policy as email_policy
from email.parser import BytesParser
from email.errors import MessageError
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile

from .gateway import Conflict,digest
from .gateway_email_admission import Refused
from .gateway_email_codec import MAX_RAW
from .gateway_media import MAX_BYTES,MAX_IMAGE_BYTES,MAX_FILES,approved,describe,authorize


def _parse_parts(raw):
    if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_RAW:raise Refused('unsupported-content')
    try:message=BytesParser(policy=email_policy.default).parsebytes(raw)
    except (ValueError,RecursionError,UnicodeError):raise Refused('unsupported-content') from None
    stack=[(message,0)];count=0;parts=[];images=0
    while stack:
        part,depth=stack.pop();count+=1
        if depth>16 or count>128 or part.defects:raise Refused('unsupported-content')
        for name in ['Content-Type','Content-Disposition','Content-Transfer-Encoding']:
            headers=part.get_all(name,[])
            if len(headers)>1 or any(getattr(value,'defects',[]) for value in headers):raise Refused('unsupported-content')
        mime=part.get_content_type().lower();disposition=part.get_content_disposition()
        # Same attachment/inline selection as the native helper, normalized by
        # the stdlib MIME parser before passing an isolated copy to that helper.
        attachment=disposition=='attachment' or disposition=='inline' and mime not in {'text/plain','text/html'}
        if part.is_multipart():
            if attachment:raise Refused('unsupported-content')  # No nested message/archive expansion.
            payload=part.get_payload()
            if not isinstance(payload,list) or len(payload)+len(stack)>128:raise Refused('unsupported-content')
            stack.extend((child,depth+1) for child in reversed(payload));continue
        if not attachment:continue
        if len(parts)>=MAX_FILES:raise Refused('unsupported-content')
        if not re.fullmatch(r'[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}',mime):
            raise Refused('unsupported-content')
        filename=part.get_filename() or ''
        if (not isinstance(filename,str) or len(filename.encode())>512
                or any(ord(c)<32 or ord(c)==127 for c in filename)):raise Refused('unsupported-content')
        try:data=part.get_payload(decode=True)
        except (ValueError,UnicodeError):raise Refused('unsupported-content') from None
        if part.defects or not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES:raise Refused('unsupported-content')
        kind=('image' if mime in {'image/png','image/jpeg'} else 'voice' if mime.startswith('audio/')
            else 'video' if mime.startswith('video/') else 'document')
        try:meta=describe(data,kind)
        except ValueError:raise Refused('unsupported-content') from None
        if kind=='image':
            if mime!='image/'+meta['format']:raise Refused('unsupported-content')
            images+=len(data)
            if images>MAX_IMAGE_BYTES:raise Refused('unsupported-content')
        if kind=='video' and mime not in {'video/mp4','video/3gpp','video/3gpp2'}:raise Refused('unsupported-content')
        index=len(parts);extension=meta['format'] if kind=='image' else 'bin'
        # Original names are never host paths. GIF/WebP and other binary files
        # remain documents under the existing PNG/JPEG model-image contract.
        parts.append({'metadata':{'index':index,'mime':mime,'kind':kind,'sha256':meta['sha256'],
            'size':len(data),'filename_sha256':hashlib.sha256(filename.encode()).hexdigest(),
            'native_filename':f'attachment-{index}.{extension}'},'data':data})
    return parts


def _parts(raw):
    try:return _parse_parts(raw)
    except (ValueError,RecursionError,UnicodeError,LookupError,MessageError):raise Refused('unsupported-content') from None


def manifest(raw):return [item['metadata'] for item in _parts(raw)]


def permit(policy,connector,envelope,items):
    binding=policy.authorize(connector,envelope)
    for item in items:
        if not approved(binding,item['kind']) or 'create' not in binding['capabilities']:
            raise Refused('media-not-approved')
    if items and envelope['text'].lstrip().startswith('/'):raise Refused('unsupported-content')
    return binding


def native_bytes(adapter,raw,expected,current):
    """Call the original frozen helper in a new private disposable cache home."""
    parts=_parts(raw)
    if [part['metadata'] for part in parts]!=expected:raise Conflict('retained email MIME manifest changed')
    if not parts:return []
    from email.message import EmailMessage
    from .gateway_matrix_profile import scope
    from plugins.platforms.email.adapter import _extract_attachments
    message=EmailMessage();message.make_mixed()
    for item in parts:
        major,minor=item['metadata']['mime'].split('/',1)
        message.add_attachment(item['data'],maintype=major,subtype=minor,filename=item['metadata']['native_filename'])
    current();result=[]
    with tempfile.TemporaryDirectory(prefix='mime-',dir=adapter._haos_email_home) as name:
        home=Path(name)
        with scope(home,adapter._haos_email_environment):decoded=_extract_attachments(message,skip_attachments=False)
        if len(decoded)!=len(parts):raise Refused('unsupported-content')
        for actual,wanted in zip(decoded,parts):
            current();meta=wanted['metadata'];path=Path(actual['path'])
            if (not path.is_absolute() or not path.resolve(strict=True).is_relative_to(home)
                    or actual['filename']!=meta['native_filename'] or actual['media_type']!=meta['mime']
                    or actual['type']!=('image' if meta['kind']=='image' else 'document')):
                raise PermissionError('native email attachment escaped its private codec context')
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            try:
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1 or info.st_size!=meta['size']:
                    raise PermissionError('exact native private MIME cache file required')
                os.fchmod(fd,0o600)
                with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(MAX_BYTES+1)
            finally:os.close(fd)
            if data!=wanted['data'] or hashlib.sha256(data).hexdigest()!=meta['sha256']:
                raise Conflict('actual native email attachment bytes changed')
            result.append({'metadata':meta,'data':data});current()
    return result


def retained(adapter,row,resource):
    from .gateway_media_relay import MediaCache
    native=adapter._haos_native;expected=row['payload'].get('media',[])
    if manifest(resource['content'])!=expected:raise Conflict('retained email MIME metadata changed')
    def current():
        adapter._haos_email_check();policy=native.policy();policy.current_binding(row)
        permit(policy,native.connector,row['envelope'],expected);return policy
    current();cache=MediaCache(native.inbox);db=native.inbox.db
    db.execute('''CREATE TABLE IF NOT EXISTS email_input_media(
        input_id TEXT NOT NULL,part_index INTEGER NOT NULL,fingerprint TEXT NOT NULL,upload_id TEXT NOT NULL,
        PRIMARY KEY(input_id,part_index))''')
    old=db.execute('SELECT * FROM email_input_media WHERE input_id=? ORDER BY part_index',(row['id'],)).fetchall()
    copied=None;result=[]
    for meta in expected:
        fingerprint=digest([row['binding_digest'],row['fingerprint'],meta])
        prior=next((item for item in old if item['part_index']==meta['index']),None)
        if prior is not None:
            if prior['fingerprint']!=fingerprint:raise Conflict('retained MIME part changed source or grant')
            item=cache.replay(current(),prior['upload_id'])
        else:
            cache.capacity()
            if copied is None:copied=native_bytes(adapter,resource['content'],expected,current)
            data=copied[meta['index']]['data']
            if any(secret.encode() in data for secret in native.inbox.redactor.secrets):raise Refused('unsupported-content')
            authorize(current(),native.connector,row['envelope'],meta['kind'])
            item=cache.put(current(),native.connector,row['envelope'],data,meta['kind'])
            db.execute('INSERT INTO email_input_media VALUES(?,?,?,?)',(row['id'],meta['index'],fingerprint,item['id']))
        if item['id'] not in {value['item']['id'] for value in result}:result.append({'metadata':meta,'item':item})
    return result
