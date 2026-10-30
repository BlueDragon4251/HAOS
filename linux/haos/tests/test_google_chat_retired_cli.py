"""Historical CLI freezes the inspected row and never accepts secret payloads."""
import argparse
from types import SimpleNamespace

import pytest

from haos import google_chat_retired_cli as cli


def args(**changes):
    value=dict(retired_action='purge-unassociated-output',profile=None,id='a'*64,snapshot_sha256='b'*64,
        note='independent Owner review',confirm_inspected=True)
    return SimpleNamespace(**{**value,**changes})


def test_nested_parser_preserves_owner_gateway_dispatch():
    parser=argparse.ArgumentParser();parser.set_defaults(action='gateway')
    cli.arguments(parser.add_subparsers(dest='gateway_action',required=True))
    result=parser.parse_args(['google-chat-retired','outputs','--profile','google-chat-'+'c'*64])
    assert (result.action,result.gateway_action,result.retired_action)==('gateway','google-chat-retired','outputs')


def test_root_gate_precedes_any_historical_read(monkeypatch):
    from haos import initial_setup
    monkeypatch.setattr(initial_setup.os,'geteuid',lambda:1000)
    monkeypatch.setattr(cli.owner,'unassociated_outputs',lambda:pytest.fail('Root gate bypassed'))
    with pytest.raises(PermissionError):cli.run(args())


def test_real_owner_gateway_dispatch_reaches_historical_command_only_after_root_gate(monkeypatch):
    from haos import gateway_setup
    selected=args();selected.gateway_action='google-chat-retired';calls=[]
    monkeypatch.setattr(gateway_setup.os,'geteuid',lambda:1000)
    monkeypatch.setattr(cli,'run',lambda value:calls.append(value) or {'historical':True})
    with pytest.raises(PermissionError):gateway_setup.owner_gateway(selected)
    assert not calls
    monkeypatch.setattr(gateway_setup.os,'geteuid',lambda:0)
    assert gateway_setup.owner_gateway(selected)=={'historical':True} and calls==[selected]


@pytest.mark.parametrize('change',[{'confirm_inspected':False},{'snapshot_sha256':'bad'},{'note':''},{'profile':'google-chat-'+'c'*64}])
def test_invalid_global_decisions_do_not_access_private_worker(monkeypatch,change):
    from haos import initial_setup
    monkeypatch.setattr(initial_setup,'require_root',lambda:None)
    monkeypatch.setattr(cli.owner,'unassociated_outputs',lambda:pytest.fail('invalid decision reached worker'))
    with pytest.raises(ValueError):cli.run(args(**change))


def test_global_cleanup_requires_exact_snapshot_from_fresh_metadata(monkeypatch):
    from haos import initial_setup
    monkeypatch.setattr(initial_setup,'require_root',lambda:None)
    row={'id':'a'*64,'snapshot_sha256':'b'*64,'purge_allowed':True};calls=[]
    monkeypatch.setattr(cli.owner,'unassociated_outputs',lambda:{'result':{'outputs':[row]}})
    monkeypatch.setattr(cli.owner,'purge_unassociated_output',lambda selected,note,**kw:calls.append((selected,note,kw)) or {'receipt':'c'*64})
    with pytest.raises(PermissionError):cli.run(args(snapshot_sha256='d'*64))
    assert not calls
    assert cli.run(args())=={'receipt':'c'*64}
    assert calls==[(row,'independent Owner review',{'confirmed':True})]


@pytest.mark.parametrize('action,method,kind',[('revoke-token','revoke','tokens'),('dispose-capsule','dispose','quarantines'),('purge-output','purge_output','outputs')])
def test_account_decision_uses_actual_worker_account_and_selected_snapshot(monkeypatch,action,method,kind):
    from haos import initial_setup
    monkeypatch.setattr(initial_setup,'require_root',lambda:None)
    account={'profile':'google-chat-'+'c'*64,'identity_sha256':'e'*64};row={'id':'a'*64,'snapshot_sha256':'b'*64};calls=[]
    monkeypatch.setattr(cli.owner,kind,lambda profile:{'account':account,'result':{kind:[row]}})
    monkeypatch.setattr(cli.owner,method,lambda app,selected,note,**kw:calls.append((app,selected,note,kw)) or {'ok':True})
    assert cli.run(args(retired_action=action,profile=account['profile']))=={'ok':True}
    assert calls==[(account,row,'independent Owner review',{'confirmed':True})]
