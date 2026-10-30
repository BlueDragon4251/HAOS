"""Fixed private interpreter and finite no-send Buzz owner responses."""
from pathlib import Path
import re
import stat

from .gateway import digest
from .gateway_buzz import HEX,scope

ERRORS=frozenset({'sdk-unavailable','authority-refused','storage-unavailable','authentication-refused',
    'rate-limited','identity-refused','transport-unavailable','private-reflection'})


def command():
    root=Path('/usr/lib/haos');python=root/'hermes/.venv/bin/python'
    for path in [root,root/'haos',root/'hermes',root/'hermes/.venv',python.parent]:
        own=path.lstat()
        if not stat.S_ISDIR(own.st_mode) or own.st_uid!=0 or own.st_mode&0o022:
            raise PermissionError('root-owned private Buzz owner runtime required')
    own=python.resolve(strict=True).lstat()
    if not stat.S_ISREG(own.st_mode) or own.st_uid!=0 or own.st_mode&0o022:raise PermissionError('root-owned private Buzz interpreter required')
    return [str(python),'-E','-s','-m','haos.buzz_owner_worker']


def response(value,action,account):
    if isinstance(value,dict) and set(value)=={'error'}:
        if not isinstance(value['error'],str) or value['error'] not in ERRORS:raise ValueError('finite Buzz owner diagnostic required')
        return value
    if not isinstance(value,dict):raise ValueError('closed no-send Buzz owner response required')
    if action=='account':
        if (set(value)!={'runtime_ready','identity_verified','read_query_succeeded','account_scope','channels_checked',
                'message_sent','mission_created','grants_changed','external_acceptance_verified'}
                or any(value[key] is not True for key in ['runtime_ready','identity_verified','read_query_succeeded'])
                or any(value[key] is not False for key in ['message_sent','mission_created','grants_changed','external_acceptance_verified'])
                or value['account_scope']!=scope(account) or type(value['channels_checked']) is not int
                or value['channels_checked']!=len(account['channels'])):raise ValueError('exact private no-send Buzz account result required')
    elif action=='outputs':
        if (set(value)!={'outputs','history_truncated','network_requested','private_bytes_returned'}
                or value['network_requested'] is not False or value['private_bytes_returned'] is not False
                or type(value['history_truncated']) is not bool or not isinstance(value['outputs'],list) or len(value['outputs'])>128):
            raise ValueError('bounded no-network Buzz output inventory required')
        fields={'id','delivery_id','name','source_sha256','state','source_bytes','stored_bytes','created_at','current_grant',
            'purge_allowed','retry_approvals','metadata_sha256','private_bytes_returned','snapshot_sha256'}
        for row in value['outputs']:
            if (not isinstance(row,dict) or set(row)!=fields or any(not isinstance(row[key],str) or not HEX.fullmatch(row[key])
                    for key in ['id','delivery_id','source_sha256','metadata_sha256','snapshot_sha256'])
                    or not isinstance(row['name'],str) or not re.fullmatch('result-[0-9]{1,6}(?:\\.[a-z0-9]{1,11})?',row['name'])
                    or not isinstance(row['state'],str) or row['state'] not in {'uploading','retry-approved','ready','purged'}
                    or any(type(row[key]) is not int or not 0<=row[key]<=8388608 for key in ['source_bytes','stored_bytes'])
                    or type(row['retry_approvals']) is not int or not 0<=row['retry_approvals']<=2
                    or any(type(row[key]) is not bool for key in ['current_grant','purge_allowed'])
                    or row['current_grant']==row['purge_allowed'] or row['private_bytes_returned'] is not False
                    or type(row['created_at']) not in {int,float} or not 0<row['created_at']<=253402300799
                    or row['snapshot_sha256']!=digest({key:item for key,item in row.items() if key!='snapshot_sha256'})):
                raise ValueError('exact private Buzz output snapshot required')
    elif action=='decide-output':
        if (set(value)!={'id','action','receipt','network_requested','message_sent','tombstones_retained','other_copies_backups_and_WAL_erasure_not_claimed'}
                or any(not isinstance(value[key],str) or not HEX.fullmatch(value[key]) for key in ['id','receipt'])
                or not isinstance(value['action'],str) or value['action'] not in {'retry-upload','purge-upload'}
                or value['network_requested'] is not False or value['message_sent'] is not False
                or value['tombstones_retained'] is not True or value['other_copies_backups_and_WAL_erasure_not_claimed'] is not True):
            raise ValueError('finite no-send Buzz upload decision receipt required')
    elif action=='outgoing':
        if (set(value)!={'outgoing','network_requested'} or value['network_requested'] is not False
                or not isinstance(value['outgoing'],list) or len(value['outgoing'])>64):raise ValueError('bounded Buzz outbox inspection required')
        for row in value['outgoing']:
            if (not isinstance(row,dict) or set(row)!={'platform','connector','delivery_id','attempt','state','native_acceptance_receipt',
                    'signed_event_id','error','updated_at','recipient_read_verified','snapshot_sha256'} or row['platform']!='buzz'
                    or not isinstance(row['connector'],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',row['connector'])
                    or any(not isinstance(row[key],str) or not HEX.fullmatch(row[key]) for key in ['delivery_id','snapshot_sha256'])
                    or any(row[key] is not None and (not isinstance(row[key],str) or not HEX.fullmatch(row[key]))
                        for key in ['native_acceptance_receipt','signed_event_id'])
                    or type(row['attempt']) is not int or not 1<=row['attempt']<=5
                    or not isinstance(row['state'],str) or row['state'] not in {'writing','uncertain','rejected','confirmed','owner-retry-approved'}
                    or row['error'] is not None and (not isinstance(row['error'],str) or row['error'] not in {'delivery-unknown','prepublication-refused'})
                    or type(row['updated_at']) not in {int,float} or not 0<row['updated_at']<=253402300799
                    or row['recipient_read_verified'] is not False):raise ValueError('closed Buzz outbox snapshot required')
    elif action=='approve-retry':
        if (set(value)!={'delivery_id','attempt','private_retry_approved','signed_event_reuse_required','network_requested','message_sent'}
                or not isinstance(value['delivery_id'],str) or not HEX.fullmatch(value['delivery_id'])
                or type(value['attempt']) is not int or not 1<=value['attempt']<5
                or value['private_retry_approved'] is not True or type(value['signed_event_reuse_required']) is not bool
                or value['network_requested'] is not False or value['message_sent'] is not False):raise ValueError('closed no-send Buzz retry approval required')
    elif action=='source-profiles':
        from .gateway_buzz_source_recovery import profile_name
        if (set(value)!={'profiles','history_truncated','network_requested','private_bytes_returned'}
                or not isinstance(value['profiles'],list) or len(value['profiles'])>128 or type(value['history_truncated']) is not bool
                or value['network_requested'] is not False or value['private_bytes_returned'] is not False):raise ValueError('bounded Buzz profile inventory required')
        for name in value['profiles']:profile_name(name)
    elif action in {'sources','history'}:
        from .gateway_buzz_source_recovery import profile_name
        if (set(value)!={'profile',action,'history_truncated','network_requested','private_bytes_returned'}
                or not isinstance(value[action],list) or len(value[action])>128 or type(value['history_truncated']) is not bool
                or value['network_requested'] is not False or value['private_bytes_returned'] is not False):raise ValueError('bounded no-payload Buzz recovery inventory required')
        profile_name(value['profile'])
        source_fields={'profile','id','connector','event_id','binding_id','binding_digest','received_at','admitted_receipt','source_sha256',
            'stored_bytes','purged','current_grant','purge_allowed','original_bytes_match_receipt','signature_reverified','metadata_sha256',
            'actual_sha256','state','snapshot_sha256'}
        history_fields={'profile','channel','pin','floor_ts','ceiling_ts','before_ts','before_id','revision','complete','current_pin',
            'current_earliest','page_sha256','reset_allowed','state','snapshot_sha256'}
        for row in value[action]:
            if (not isinstance(row,dict) or set(row)!=(source_fields if action=='sources' else history_fields)
                    or row['profile']!=value['profile'] or row['snapshot_sha256']!=digest({key:item for key,item in row.items() if key!='snapshot_sha256'})):
                raise ValueError('closed exact Buzz recovery snapshot required')
            hashes=['id','event_id','binding_digest','source_sha256','metadata_sha256'] if action=='sources' else ['pin','page_sha256']
            if any(not isinstance(row[key],str) or not HEX.fullmatch(row[key]) for key in hashes):raise ValueError('exact Buzz recovery proof hashes required')
            if action=='sources':
                if (type(row['stored_bytes']) is not int or not 0<=row['stored_bytes']<=1048576
                        or row['state'] not in {'retained','purged','damaged'} or row['signature_reverified'] is not False
                        or any(type(row[key]) is not bool for key in ['purged','current_grant','purge_allowed','original_bytes_match_receipt'])
                        or not isinstance(row['admitted_receipt'],str) or row['admitted_receipt'] and not HEX.fullmatch(row['admitted_receipt'])
                        or row['actual_sha256'] is not None and (not isinstance(row['actual_sha256'],str) or not HEX.fullmatch(row['actual_sha256']))):
                    raise ValueError('finite Buzz source byte status required')
                for key in ['connector','binding_id']:
                    if not isinstance(row[key],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',row[key]):raise ValueError('bounded Buzz source route identity required')
                if type(row['received_at']) not in {int,float} or not 0<row['received_at']<=253402300799:raise ValueError('finite Buzz source arrival time required')
            else:
                from .gateway_buzz import channel
                channel(row['channel'])
                if (any(type(row[key]) is not int or not 0<row[key]<2**53 for key in ['floor_ts','ceiling_ts','before_ts'])
                        or type(row['revision']) is not int or not 0<=row['revision']<2**53 or row['complete'] not in {0,1}
                        or type(row['reset_allowed']) is not bool or row['state'] not in {'current','grant-changed','unpaired'}
                        or row['current_pin'] is not None and (not isinstance(row['current_pin'],str) or not HEX.fullmatch(row['current_pin']))
                        or row['current_earliest'] is not None and (type(row['current_earliest']) is not int or not 0<row['current_earliest']<2**53)):
                    raise ValueError('finite Buzz history checkpoint required')
    elif action in {'purge-source','reset-history'}:
        expected=({'id','receipt','network_requested','message_sent','tombstones_retained','other_copies_backups_and_WAL_erasure_not_claimed'}
            if action=='purge-source' else {'channel','receipt','network_requested','message_sent','originals_and_previous_checkpoint_receipt_retained'})
        if (set(value)!=expected or not isinstance(value['receipt'],str) or not HEX.fullmatch(value['receipt'])
                or value['network_requested'] is not False or value['message_sent'] is not False):raise ValueError('closed no-send Buzz source/history receipt required')
        if action=='purge-source':
            if not isinstance(value['id'],str) or not HEX.fullmatch(value['id']) or value['tombstones_retained'] is not True or value['other_copies_backups_and_WAL_erasure_not_claimed'] is not True:
                raise ValueError('explicit retained Buzz source tombstone required')
        else:
            from .gateway_buzz import channel
            channel(value['channel'])
            if value['originals_and_previous_checkpoint_receipt_retained'] is not True:raise ValueError('Buzz cursor reset must retain originals and inspected previous proof')
    elif action=='retry-auth':
        if (set(value)!={'connector','authentication_blocks_cleared','network_requested','message_sent'}
                or not isinstance(value['connector'],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',value['connector'])
                or type(value['authentication_blocks_cleared']) is not int or not 0<=value['authentication_blocks_cleared']<=65536
                or value['network_requested'] is not False or value['message_sent'] is not False):raise ValueError('finite no-send Buzz auth recheck result required')
    else:raise ValueError('unsupported public Buzz owner response')
    return value
