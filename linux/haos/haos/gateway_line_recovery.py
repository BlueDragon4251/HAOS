"""Bounded private LINE server-acceptance inspection, without message or tokens."""
import math
import re

_HASH=re.compile(r'[0-9a-f]{64}\Z')


def outgoing(inbox,platform='line'):
    if platform not in {'line','sms'}:raise ValueError('reviewed private receipt platform required')
    table=platform+'_delivery_intents'
    if not inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():return []
    result=[]
    for row in inbox.db.execute(f'SELECT delivery_id,attempt,state,receipt,updated_at FROM {table} ORDER BY updated_at DESC LIMIT 64'):
        if (not isinstance(row['delivery_id'],str) or not _HASH.fullmatch(row['delivery_id'])
                or type(row['attempt']) is not int or not 1<=row['attempt']<=5
                or row['state'] not in {'writing','confirmed','uncertain'}
                or not isinstance(row['receipt'],str)
                or row['state']=='confirmed' and not re.fullmatch(platform+r'_push_[0-9a-f]{64}',row['receipt'])
                or row['state']!='confirmed' and row['receipt']
                or type(row['updated_at']) not in {int,float} or not math.isfinite(row['updated_at']) or row['updated_at']<0):
            raise ValueError('invalid private LINE server acceptance metadata')
        result.append({'platform':platform,'delivery_id':row['delivery_id'],'attempt':row['attempt'],
            'state':row['state'],'server_acceptance_receipt':row['receipt'] or None,
            'updated_at':row['updated_at'],'recipient_receipt_verified':False})
    return result
