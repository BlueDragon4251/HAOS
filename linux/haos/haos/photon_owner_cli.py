"""Payload-free historical recovery; no activation or account login implied."""


def arguments(gateway_sub):
    parser = gateway_sub.add_parser('photon-recovery', help='inspect recorded Photon status or explicitly dispose retired originals; sends no messages')
    parser.add_argument('photon_action', choices=['status', 'profiles', 'sources', 'purge-source', 'retry-auth'])
    parser.add_argument('--connector'); parser.add_argument('--profile'); parser.add_argument('--id')
    parser.add_argument('--snapshot-sha256'); parser.add_argument('--note'); parser.add_argument('--confirm-inspected', action='store_true')
    parser.add_argument('--status-sha256')


def run(args):
    from .initial_setup import require_root
    require_root()
    from . import photon_owner_setup as owner
    action = args.photon_action
    if action not in {'status', 'retry-auth'} and args.connector: raise ValueError('connector selector applies only to recorded status or auth retry')
    if action != 'retry-auth' and args.status_sha256: raise ValueError('status inspection hash applies only to auth retry')
    if action == 'status':
        if not args.connector or any([args.profile, args.id, args.snapshot_sha256, args.note, args.confirm_inspected]):
            raise ValueError('recorded status takes only the exact --connector')
        from .gateway_photon_auth_retry import inspection
        value = owner.status(args.connector)
        return value if 'error' in value else {**value, 'auth_retry_snapshot_sha256': inspection(value['result'])}
    if action == 'retry-auth':
        if not args.connector or args.profile or args.id or args.snapshot_sha256:
            raise ValueError('auth retry takes only an exact connector and recorded status inspection')
        from .gateway_photon_auth_retry import inspection, HEX
        if (not isinstance(args.status_sha256, str) or not HEX.fullmatch(args.status_sha256) or args.confirm_inspected is not True
                or not isinstance(args.note, str) or not 1 <= len(args.note.strip()) <= 2000):
            raise ValueError('exact --status-sha256 --note and --confirm-inspected required')
        value = owner.status(args.connector)
        if 'error' in value: return value
        if inspection(value['result']) != args.status_sha256: raise PermissionError('Photon status changed; inspect again before permitting retry')
        return owner.retry_auth(args.connector, value['result'], args.note, confirmed=True)
    if action == 'profiles':
        if any([args.profile, args.id, args.snapshot_sha256, args.note, args.confirm_inspected]):
            raise ValueError('retained profile inventory takes no selector or mutation')
        return owner.profiles()
    if not args.profile: raise ValueError('select the exact retained --profile')
    if action == 'sources':
        if any([args.id, args.snapshot_sha256, args.note, args.confirm_inspected]): raise ValueError('source inspection takes no disposal decision')
        return owner.sources(args.profile)
    return owner.purge(args.profile, args.id, args.snapshot_sha256, args.note, confirmed=args.confirm_inspected)
