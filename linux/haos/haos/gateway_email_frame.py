"""Exact binary snapshot tail for the private SMTP worker's bounded JSON header."""
import hashlib
from .gateway_email_smtp import descriptors
from .gateway_media import CHUNK_BYTES


def validate(metadata,parts):
    metadata=descriptors(metadata)
    if not isinstance(parts,(list,tuple)) or len(parts)!=len(metadata):raise ValueError('every SMTP snapshot needs exact private bytes')
    for item,data in zip(metadata,parts):
        if not isinstance(data,bytes) or len(data)!=item['size'] or hashlib.sha256(data).hexdigest()!=item['sha256']:
            raise ValueError('private SMTP snapshot bytes differ from their declared receipt')
    return metadata


def read(stream,metadata,current):
    metadata=descriptors(metadata);parts=[]
    for item in metadata:
        data=bytearray();checksum=hashlib.sha256()
        while len(data)<item['size']:
            current();block=stream.read(min(CHUNK_BYTES,item['size']-len(data)));current()
            if not block:raise ValueError('incomplete private SMTP snapshot stream')
            data.extend(block);checksum.update(block)
        if checksum.hexdigest()!=item['sha256']:raise ValueError('private SMTP snapshot checksum changed')
        parts.append(bytes(data))
    current()
    if stream.read(1):raise ValueError('unexpected bytes after the private SMTP snapshots')
    current();return parts
