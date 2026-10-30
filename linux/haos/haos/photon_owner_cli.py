"""Payload-free historical recovery; no activation or account login implied."""


def arguments(gateway_sub):
    parser = gateway_sub.add_parser('photon-recovery', help='inspect recorded Photon status or explicitly dispose retired originals; sends no messages')
    parser.add_argument('photon_action', choices=['status', 'profiles', 'sources', 'purge-source'])
    parser.add_argument('--connector'); parser.add_argument('--profile'); parser.add_argument('--id')
    parser.add_argument('--snapshot-sha256'); parser.add_argument('--note'); parser.add_argument('--confirm-inspected', action='store_true')


def run(args):
    from .initial_setup import require_root
    require_root()
    from . import photon_owner_setup as owner
    action = args.photon_action
    if action != 'status' and args.connector: raise ValueError('connector selector applies only to recorded status')
    if action == 'status':
        if not args.connector or any([args.profile, args.id, args.snapshot_sha256, args.note, args.confirm_inspected]):
            raise ValueError('recorded status takes only the exact --connector')
        return owner.status(args.connector)
    if action == 'profiles':
        if any([args.profile, args.id, args.snapshot_sha256, args.note, args.confirm_inspected]):
            raise ValueError('retained profile inventory takes no selector or mutation')
        return owner.profiles()
    if not args.profile: raise ValueError('select the exact retained --profile')
    if action == 'sources':
        if any([args.id, args.snapshot_sha256, args.note, args.confirm_inspected]): raise ValueError('source inspection takes no disposal decision')
        return owner.sources(args.profile)
    return owner.purge(args.profile, args.id, args.snapshot_sha256, args.note, confirmed=args.confirm_inspected)
