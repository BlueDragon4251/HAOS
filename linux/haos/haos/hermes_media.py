"""Bounded native attachment RPCs; callers never supply gateway/host paths."""
import base64
import hashlib
from pathlib import PurePosixPath
import re

from .gateway_media import describe,descriptor,MAX_FILES


async def attach(connection,session_id,items):
    if not isinstance(session_id,str) or not 1<=len(session_id)<=128 or any(ord(c)<32 for c in session_id):
        raise ValueError('exact native session identity required')
    if not isinstance(items,list) or len(items)>MAX_FILES:raise ValueError('bounded mission attachment list required')
    refs=[]
    for item in items:
        meta=descriptor(item['descriptor']);data=item['data']
        if describe(data,meta['kind'])!=meta:raise ValueError('mission attachment bytes changed')
        stem='attachment-'+meta['sha256']+'-'+hashlib.sha256(session_id.encode()).hexdigest()[:16]
        extension='jpg' if meta['format']=='jpeg' else meta['format']
        name=stem+'.'+extension
        encoded=base64.b64encode(data).decode('ascii')
        if meta['kind']=='image':
            result=await connection.request('image.attach_bytes',{'session_id':session_id,'content_base64':encoded,'filename':name})
            if not isinstance(result,dict) or result.get('attached') is not True or result.get('bytes')!=len(data):
                raise ValueError('native image attachment was not acknowledged')
        else:
            result=await connection.request('file.attach',{'session_id':session_id,'data_url':'data:application/octet-stream;base64,'+encoded,'name':name})
            ref=result.get('ref_text') if isinstance(result,dict) else None
            allocated=result.get('name') if isinstance(result,dict) else None
            if (not isinstance(result,dict) or result.get('attached') is not True or result.get('uploaded') is not True
                    or not isinstance(allocated,str) or not re.fullmatch(re.escape(stem)+r'(?:-[2-9][0-9]{0,5})?\.'+extension,allocated)
                    or not isinstance(ref,str) or not ref.startswith('@file:')
                    or len(ref)>2048 or any(ord(c)<32 for c in ref)):
                raise ValueError('native document attachment was not acknowledged')
            path=ref[len('@file:'):]
            if path[:1] in {'`','"',"'"}:
                if path[-1:]!=path[:1]:raise ValueError('invalid native attachment reference')
                path=path[1:-1]
            if PurePosixPath(path).name!=allocated or '..' in PurePosixPath(path).parts:
                raise ValueError('native attachment reference changed identity')
            refs.append(ref)
    return refs
