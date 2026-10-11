"""Closed application capabilities shared by the existing GUI queue and authority.

These are opaque mission instances, never host window IDs, argv, environment,
clipboard, file selectors or compositor addresses.
"""
import base64
import hashlib
import json
import re
import uuid

from .application_session import session_action

OPERATIONS = {'app.start','app.state','app.focus','app.type','app.key','app.capture','app.close'}


def identifier(value):
    if not isinstance(value,str) or str(uuid.UUID(value))!=value:
        raise ValueError('canonical application instance UUID required')
    return value


def action(value):
    if not isinstance(value,dict) or value.get('operation') not in OPERATIONS:
        raise PermissionError('application capability denied')
    op=value['operation']
    if op=='app.start':
        if set(value)!={'operation','program'} or not isinstance(value['program'],str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',value['program']):
            raise PermissionError('only an exact owner-registered application is allowed')
    else:
        identifier(value.get('instance'))
        expected={'operation','instance'} | ({'text'} if op=='app.type' else {'key'} if op=='app.key' else set())
        if set(value)!=expected:
            raise PermissionError('unexpected application capability parameters')
        if op!='app.close':
            session_action({'operation':op.removeprefix('app.'),**{k:v for k,v in value.items() if k not in {'operation','instance'}}})
    return dict(value)


def action_digest(value):
    # Identical canonical encoding to the persistent GUI admission. The root
    # authority computes this from validated input, never accepts a caller hash.
    return hashlib.sha256(json.dumps(action(value),sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def receipt(op,value):
    if op not in OPERATIONS or not isinstance(value,dict):
        raise ValueError('invalid application receipt')
    identifier(value.get('instance'))
    fields={'instance'}
    if op=='app.start':
        fields|={'program','state'}
        if not isinstance(value.get('program'),str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',value['program']) or value.get('state')!='submitted':
            raise ValueError('invalid application admission receipt')
    elif op=='app.state':
        fields|={'running','windows','window_state_sha256','application_exitcode'}
        if (type(value.get('running')) is not bool or type(value.get('windows')) is not int or not 0<=value['windows']<=32
                or value.get('application_exitcode') is not None and (type(value['application_exitcode']) is not int or not -255<=value['application_exitcode']<=255)
                or not isinstance(value.get('window_state_sha256'),str) or not re.fullmatch(r'[a-f0-9]{64}',value['window_state_sha256'])):
            raise ValueError('invalid observed application state')
    elif op in {'app.focus','app.type','app.key'}:
        flag='focused' if op=='app.focus' else 'applied';fields.add(flag)
        if value.get(flag) is not True: raise ValueError('invalid application input receipt')
    elif op=='app.close':
        fields.add('state')
        if value.get('state')!='stopped':raise ValueError('unconfirmed application termination')
    else:
        fields|={'mime','sha256','bytes','base64'}
        if value.get('mime')!='image/jpeg' or not isinstance(value.get('base64'),str) or len(value['base64'])>1398104:
            raise ValueError('application capture budget exceeded')
        pixels=base64.b64decode(value['base64'],validate=True)
        if (type(value.get('bytes')) is not int or not 100<=len(pixels)<=1048576 or len(pixels)!=value['bytes']
                or hashlib.sha256(pixels).hexdigest()!=value.get('sha256') or not pixels.startswith(b'\xff\xd8') or not pixels.endswith(b'\xff\xd9')):
            raise ValueError('invalid actual compositor capture')
    if set(value)!=fields:raise ValueError('unexpected application receipt parameters')
    return value
