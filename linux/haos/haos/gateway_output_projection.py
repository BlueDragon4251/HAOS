"""Project complete controller markup into original durable chunks without fence loss."""
from .gateway_outbound import marked


def project(chunks):
    if not isinstance(chunks,list) or not chunks or any(not isinstance(c,str) for c in chunks):
        raise ValueError('complete ordered controller text chunks required')
    body=''.join(chunks);allowed,_=marked(body);drops=[];offset=0;fence=None
    for line in body.splitlines(keepends=True):
        text=line.strip();start=offset;offset+=len(line)
        if text.startswith(('```','~~~')):
            marker=text[:3];fence=None if fence==marker else marker if fence is None else fence
        elif fence is None and text.startswith('MEDIA:'):
            paths,_=marked(line)
            if len(paths)!=1 or paths[0] not in allowed:raise ValueError('controller media marker differs from full output grammar')
            drops.append((start,offset,paths[0]))
        elif fence is None and text in {'[[audio_as_voice]]','[[as_document]]'}:drops.append((start,offset,None))
    result=[];offset=0;seen=set()
    for chunk in chunks:
        start=offset;end=start+len(chunk);offset=end;cursor=start;pieces=[];paths=[]
        for left,right,path in drops:
            if right<=start or left>=end:continue
            if path is not None and (left<start or right>end):raise ValueError('controller output split a media marker across chunks')
            pieces.append(body[cursor:max(cursor,left)]);cursor=max(cursor,min(right,end))
            if path is not None and path not in seen:paths.append(path);seen.add(path)
        pieces.append(body[cursor:end]);result.append({'text':''.join(pieces),'paths':paths})
    return result
