"""No-message Owner CLI for retained Google app metadata and withdrawal."""
from . import google_chat_retired_setup as owner


def arguments(gateway_sub):
    parser=gateway_sub.add_parser('google-chat-retired',help='inspect retained app metadata or explicitly withdraw access; never sends messages')
    parser.add_argument('retired_action',choices=['profiles','tokens','quarantines','outputs','unassociated-outputs',
        'revoke-token','dispose-capsule','purge-output','purge-unassociated-output','restore-identity'])
    parser.add_argument('--profile');parser.add_argument('--id');parser.add_argument('--snapshot-sha256')
    parser.add_argument('--note');parser.add_argument('--confirm-inspected',action='store_true')
    for key in ['project-id','service-account-email','bot-user']:parser.add_argument('--'+key)


def run(args):
    from .initial_setup import require_root
    require_root()
    action=args.retired_action
    inspection={'profiles','tokens','quarantines','outputs','unassociated-outputs'}
    global_action=action in {'profiles','unassociated-outputs','purge-unassociated-output'}
    if global_action and args.profile:raise ValueError('global recovery does not select or infer an app profile')
    if not global_action and not args.profile:raise ValueError('select the exact retained --profile')
    identity_fields={key:getattr(args,key,None) for key in ['project_id','service_account_email','bot_user']}
    if action=='restore-identity':
        if args.id or args.snapshot_sha256:raise ValueError('public identity repair uses the original profile hash, not a token or output selector')
        return owner.restore_identity(args.profile,{'version':1,**identity_fields},args.note,confirmed=args.confirm_inspected)
    if any(value is not None for value in identity_fields.values()):raise ValueError('public identity fields apply only to restore-identity')
    if action in inspection:
        if any([args.id,args.snapshot_sha256,args.note,args.confirm_inspected]):raise ValueError('inspection takes no withdrawal decision')
        if action=='profiles':return owner.profiles()
        if action=='unassociated-outputs':return owner.unassociated_outputs()
        return getattr(owner,action)(args.profile)
    from .gateway_google_chat_recovery import HEX
    if (not isinstance(args.id,str) or not HEX.fullmatch(args.id) or not isinstance(args.snapshot_sha256,str)
            or not HEX.fullmatch(args.snapshot_sha256) or args.confirm_inspected is not True
            or not isinstance(args.note,str) or not 1<=len(args.note.strip())<=2000):
        raise ValueError('exact inspected --id --snapshot-sha256 --note and --confirm-inspected required')
    kind={'revoke-token':'tokens','dispose-capsule':'quarantines','purge-output':'outputs','purge-unassociated-output':'outputs'}[action]
    value=owner.unassociated_outputs() if action=='purge-unassociated-output' else getattr(owner,kind)(args.profile)
    if 'error' in value:return value
    rows=[row for row in value['result'][kind] if row['id']==args.id and row['snapshot_sha256']==args.snapshot_sha256]
    if len(rows)!=1:raise PermissionError('selected retained state changed or is outside this page; inspect again before deciding')
    row=rows[0]
    if action=='purge-unassociated-output':return owner.purge_unassociated_output(row,args.note,confirmed=True)
    return {'revoke-token':owner.revoke,'dispose-capsule':owner.dispose,'purge-output':owner.purge_output}[action](
        value['account'],row,args.note,confirmed=True)
