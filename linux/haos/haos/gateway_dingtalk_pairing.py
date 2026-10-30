"""Untrusted one-shot identity observation; never a sender grant or agent input."""
import hashlib
import json
import re
import time

from .gateway import Conflict,digest
from .gateway_dingtalk import credentials,identity,scope
from .gateway_dingtalk_admission import parse,milliseconds,Refused


def challenge(value):
    if (not isinstance(value,dict) or set(value)!={'nonce','since','until'}
            or not isinstance(value['nonce'],str) or not re.fullmatch('[0-9a-f]{32}',value['nonce'])
            or any(type(value[k]) is not int for k in ['since','until'])
            or not 0<value['since']<value['until']<2**53 or value['until']-value['since']>120000):
        raise ValueError('bounded explicit pairing challenge required')
    if not value['since']<=time.time()*1000<=value['until']:raise PermissionError('pairing observation expired')
    return dict(value)


def candidate(value,request,raw):
    value=credentials(value);request=challenge(request);data=parse(raw)
    expected='HAOS koppeln '+request['nonce']
    if (data.get('msgtype')!='text' or not isinstance(data.get('text'),dict)
            or not isinstance(data['text'].get('content'),str) or data['text']['content'].strip()!=expected):
        return None
    try:
        if any(data.get(key)!=value['corp_id'] for key in ['chatbotCorpId','senderCorpId']) or data.get('robotCode')!=value['robot_code']:
            raise Refused('wrong-account')
        sender=identity(data.get('senderId'));chat=identity(data.get('conversationId'));message=identity(data.get('msgId'))
        if sender==value['robot_code'] or data.get('senderIsRobot',False) is not False:raise Refused('self-or-automated')
        kind=data.get('conversationType')
        if not (type(kind) is int and kind in {1,2} or isinstance(kind,str) and kind in {'1','2'}):raise Refused('unsupported-content')
        if str(kind)=='2' and data.get('isInAtList') is not True:raise Refused('mention-required')
        if any(data.get(key) not in (None,'') for key in ['threadId','thread_id','topicId']):raise Refused('unsupported-thread')
        stamp=milliseconds(data.get('createAt'))
        if not request['since']<stamp<=min(request['until'],time.time()*1000+5000):raise Refused('invalid-time')
        from dingtalk_stream import ChatbotMessage
        native=ChatbotMessage.from_dict(data)
        if (native.sender_id!=sender or native.conversation_id!=chat or native.message_id!=message
                or native.text is None or native.text.content.strip()!=expected):raise Refused('changed-native-source')
    except Refused:raise
    except (ValueError,TypeError,KeyError,AttributeError):raise Refused('unsupported-content') from None
    return {'sender':sender,'chat':chat,'scope':scope(value),'thread':'','message_id':message,
        'conversation_type':str(kind),'created_at':stamp,'source_sha256':hashlib.sha256(raw).hexdigest(),
        'challenge_sha256':digest(request),'authorized':False,'mission_created':False,'message_sent':False}


class Candidates:
    def __init__(self,inbox):
        self.db=inbox.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS dingtalk_pairing_candidates(
            id TEXT PRIMARY KEY,connector TEXT NOT NULL,challenge_sha256 TEXT NOT NULL UNIQUE,
            metadata TEXT NOT NULL,created_at REAL NOT NULL)''')

    def retain(self,connector,item):
        if not isinstance(connector,str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',connector):
            raise ValueError('exact configured connector required')
        if (not isinstance(item,dict) or set(item)!={'sender','chat','scope','thread','message_id','conversation_type','created_at',
                'source_sha256','challenge_sha256','authorized','mission_created','message_sent'}
                or any(item[key] is not False for key in ['authorized','mission_created','message_sent'])):
            raise ValueError('untrusted pairing metadata required')
        for key in ['sender','chat','message_id']:identity(item[key])
        if (item['thread']!='' or item['conversation_type'] not in {'1','2'} or type(item['created_at']) is not int
                or not 0<item['created_at']<2**53 or not isinstance(item['scope'],str) or not re.fullmatch('dingtalk:[0-9a-f]{64}',item['scope'])
                or any(not isinstance(item[key],str) or not re.fullmatch('[0-9a-f]{64}',item[key]) for key in ['source_sha256','challenge_sha256'])):
            raise ValueError('canonical untrusted pairing metadata required')
        metadata=json.dumps(item,sort_keys=True,separators=(',',':'));identity_hash=digest([connector,item['challenge_sha256']])
        self.db.execute('BEGIN IMMEDIATE')
        try:
            previous=self.db.execute('SELECT * FROM dingtalk_pairing_candidates WHERE id=?',(identity_hash,)).fetchone()
            if previous is not None:
                if previous['connector']!=connector or previous['metadata']!=metadata:raise Conflict('pairing observation already retained another source')
            else:
                pages=self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0]
                if (self.db.execute('SELECT COUNT(*) FROM dingtalk_pairing_candidates').fetchone()[0]>=65536
                        or pages*self.db.execute('PRAGMA page_size').fetchone()[0]>=64*1024*1024):
                    raise Conflict('pairing observation history full; owner maintenance required')
                self.db.execute('INSERT INTO dingtalk_pairing_candidates VALUES(?,?,?,?,?)',
                    (identity_hash,connector,item['challenge_sha256'],metadata,time.time()))
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
        return identity_hash
