"""First-byte receipts and private replay for exact signed Buzz resources."""
from .gateway import Conflict,digest
from .gateway_buzz_resource import specification,fetch
from .gateway_buzz_admission import Refused
from .gateway_media import MAX_IMAGE_BYTES


async def retained(adapter,row,original,projected):
    from .gateway_media_relay import MediaCache
    native=adapter._haos_native;db=native.inbox.db;cache=MediaCache(native.inbox)
    if projected['text'].lstrip().startswith('/'):raise Refused('media-command-refused')
    native.policy().authorize(native.connector,projected)
    db.execute('''CREATE TABLE IF NOT EXISTS buzz_input_media(
        input_id TEXT NOT NULL,resource_index INTEGER NOT NULL,fingerprint TEXT NOT NULL,
        upload_id TEXT NOT NULL,mime TEXT NOT NULL,PRIMARY KEY(input_id,resource_index))''')
    result=[];images=set();image_bytes=0
    def current():
        adapter._haos_buzz_check();policy=native.policy();policy.current_binding(row);return policy
    for index,resource in enumerate(original['resources']):
        policy=current();spec=await specification(adapter,row,original,index)
        fingerprint=digest([row['binding_digest'],spec['fingerprint'],original['id'],resource,digest(projected)])
        prior=db.execute('SELECT * FROM buzz_input_media WHERE input_id=? AND resource_index=?',(row['id'],index)).fetchone()
        cached=None
        if prior is not None:
            if prior['fingerprint']!=digest([fingerprint,prior['upload_id'],prior['mime']]):raise Conflict('Buzz retained resource changed original bytes type or grant')
            if db.execute('SELECT 1 FROM native_media_cache WHERE id=?',(prior['upload_id'],)).fetchone():
                cached=cache.replay(policy,prior['upload_id']);mime=prior['mime']
        if cached is None:
            cache.capacity();reply=await fetch(adapter,row,original,index);policy=current()
            meta=reply['descriptor'];mime=reply['mime']
            expected=digest([native.connector,digest(policy.current_binding(row)),digest(projected),meta])
            if prior is not None:
                if prior['upload_id']!=expected or prior['mime']!=mime:raise Conflict('Buzz recovery changed first retained resource bytes or MIME')
            else:
                db.execute('INSERT INTO buzz_input_media VALUES(?,?,?,?,?)',(row['id'],index,digest([fingerprint,expected,mime]),expected,mime))
            cached=cache.put(policy,native.connector,projected,reply['data'],meta['kind'])
            if cached['id']!=expected:raise Conflict('Buzz cached media differs from retained first-byte receipt')
        if cached['connector']!=native.connector or cached['envelope_digest']!=digest(projected):raise Conflict('Buzz cached media belongs to another native goal or connector')
        if cached['descriptor']['kind']=='image' and cached['id'] not in images:
            images.add(cached['id']);image_bytes+=cached['descriptor']['size']
        if image_bytes>MAX_IMAGE_BYTES:raise Refused('aggregate-image-budget')
        result.append({'resource':dict(resource),'index':index,'item':cached,'mime':mime})
    current();return result
