"""Bounded private IRC delivery inspection without message text or remote raw IDs."""
import hashlib
import json
import math
import re

_HASH=re.compile(r'[0-9a-f]{64}\Z')
_STATES=frozenset({'writing','confirmed','uncertain'})


def outgoing(inbox):
    if not inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='irc_delivery_intents'").fetchone():return []
    result=[]
    for row in inbox.db.execute('SELECT * FROM irc_delivery_intents ORDER BY updated_at DESC LIMIT 64'):
        if (any(not isinstance(row[key],str) or not _HASH.fullmatch(row[key])
                for key in ('delivery_id','identity','binding_digest','content_digest'))
                or not isinstance(row['connector'],str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',row['connector'])
                or type(row['attempt']) is not int or not 1<=row['attempt']<=5
                or row['state'] not in _STATES or type(row['chunk_count']) is not int or not 1<=row['chunk_count']<=64
                or type(row['updated_at']) not in {int,float} or not math.isfinite(row['updated_at']) or row['updated_at']<0
                or not isinstance(row['receipts'],str) or len(row['receipts'].encode())>16384):
            raise ValueError('invalid private IRC delivery inspection metadata')
        try:receipts=json.loads(row['receipts'])
        except (ValueError,TypeError):raise ValueError('invalid private IRC receipt list') from None
        if (not isinstance(receipts,list) or len(receipts)>row['chunk_count']
                or any(not isinstance(item,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',item) for item in receipts)
                or len(set(receipts))!=len(receipts)
                or row['state']=='confirmed' and len(receipts)!=row['chunk_count']):
            raise ValueError('invalid private IRC confirmation metadata')
        receipt=row['receipt'] if 'receipt' in row.keys() else ''
        if (not isinstance(receipt,str) or receipt and not re.fullmatch(r'irc_echo_[0-9a-f]{64}',receipt)
                or receipt and row['state']!='confirmed'):
            raise ValueError('invalid private IRC server echo reference')
        result.append({'platform':'irc','delivery_id':row['delivery_id'],'attempt':row['attempt'],'connector':row['connector'],
            'state':row['state'],'updated_at':row['updated_at'],'binding_digest':row['binding_digest'],
            'content_sha256':row['content_digest'],'chunk_count':row['chunk_count'],'confirmed_chunks':len(receipts),
            'receipts_sha256':hashlib.sha256(row['receipts'].encode()).hexdigest(),
            'server_echo_receipt':receipt or None,'recipient_receipt_verified':False})
    return result
