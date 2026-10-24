from types import SimpleNamespace
import pytest
from haos import initial_setup


def test_root_required(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 1000)
    for call in (
        lambda: initial_setup.account_status(),
        lambda: initial_setup.create_initial_owner("secure", "X" * 25, "X" * 25),
        lambda: initial_setup.configure_region("de_AT.UTF-8", "at"),
        lambda: initial_setup.configure_update("dev", True),
        lambda: initial_setup.configure_ghcr("owner", "private"),
        lambda: initial_setup.configure_provider("openai", "gpt-model", "secret"),
        lambda: initial_setup.import_cloud_credential("vertex", "/no-such-file"),
        lambda: initial_setup.gateway_configuration(),
        lambda: initial_setup.manage_gateway("start"),
        lambda: initial_setup.manage_gateway("revoke", "fixture"),
        lambda: initial_setup.gateway_process_status(),
        lambda: initial_setup.gateway_ingress(),
        lambda: initial_setup.reconcile_gateway_ingress({}, 'retry', 'fixture'),
        lambda: initial_setup.gateway_deliveries(),
        lambda: initial_setup.reconcile_gateway_delivery({},'retry','fixture'),
        lambda: initial_setup.resume_runtime(),
    ):
        with pytest.raises(PermissionError):
            call()


def test_no_existing_owner_may_be_reenrolled(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(initial_setup, "owners", lambda: [{"username": "present", "uid": 1002}])
    with pytest.raises(PermissionError):
        initial_setup.create_initial_owner("other", "secret", "secret")


def test_graphical_native_ingress_recovery_preserves_selected_receipt_and_quiesces_first(monkeypatch):
    from haos import gateway_setup
    monkeypatch.setattr(initial_setup.os,'geteuid',lambda:0)
    calls=[]
    monkeypatch.setattr(initial_setup,'quiesce_for_setup',lambda **kwargs:calls.append(('stop',kwargs)))
    monkeypatch.setattr(gateway_setup,'owner_gateway',lambda args:calls.append(('owner',vars(args))))
    with pytest.raises(ValueError):initial_setup.gateway_ingress(-1)
    with pytest.raises(ValueError):initial_setup.reconcile_gateway_ingress({},'retry','fixture')
    assert calls==[]
    initial_setup.gateway_ingress(10)
    row={'ingress_id':'a'*64,'attempt':8,'state':'failed'}
    initial_setup.reconcile_gateway_ingress(row,'retry','inspected fixture')
    assert calls==[('stop',{'gateway_only':True}),('owner',{'gateway_action':'ingress','after':10}),
        ('stop',{'gateway_only':True}),('owner',{'gateway_action':'reconcile-ingress','ingress_id':'a'*64,
        'attempt':8,'state':'failed','decision':'retry','note':'inspected fixture'})]


def test_graphical_slack_setup_keeps_two_credentials_private_and_rejects_bad_input_before_stopping(monkeypatch):
    from haos import gateway_setup,owner
    from copy import deepcopy
    monkeypatch.setattr(initial_setup.os,'geteuid',lambda:0)
    calls=[];saved=[]
    monkeypatch.setattr(initial_setup,'quiesce_for_setup',lambda **kwargs:calls.append(kwargs))
    monkeypatch.setattr(gateway_setup,'load',lambda:({'version':1,'connectors':[],'bindings':[]},{'connectors':{}}))
    monkeypatch.setattr(gateway_setup,'persist',lambda p,c:saved.append((deepcopy(p),deepcopy(c))))
    monkeypatch.setattr(owner,'audit',lambda *args:calls.append(args))
    bot='xoxb-'+'x'*24;app='xapp-'+'y'*24
    for token,app_token in [(bot,''),(bot,bot),(bot+','+bot,app),(bot,app+'\n')]:
        with pytest.raises(ValueError):initial_setup.configure_gateway('slack-main','slack',token,app_token)
    assert calls==[] and saved==[]
    initial_setup.configure_gateway('slack-main','slack',bot,app)
    assert saved[0][1]=={'connectors':{'slack-main':{'token':bot,'app_token':app}}}
    assert calls[0]=={'gateway_only':True}
    assert bot not in repr(calls) and app not in repr(calls)


def test_graphical_delivery_retry_requires_owner_evidence_before_quiescing(monkeypatch):
    from haos import gateway_setup
    monkeypatch.setattr(initial_setup.os,'geteuid',lambda:0)
    calls=[]
    monkeypatch.setattr(initial_setup,'quiesce_for_setup',lambda **kwargs:calls.append(('stop',kwargs)))
    monkeypatch.setattr(gateway_setup,'owner_gateway',lambda args:calls.append(('owner',vars(args))))
    row={'delivery_id':'a'*64,'attempt':1,'state':'uncertain'}
    with pytest.raises(ValueError):initial_setup.gateway_deliveries(-1)
    with pytest.raises(PermissionError):initial_setup.reconcile_gateway_delivery(row,'retry','inspected')
    with pytest.raises(ValueError):initial_setup.reconcile_gateway_delivery(row,'delivered','inspected',None)
    with pytest.raises(ValueError):initial_setup.reconcile_gateway_delivery(row,'discard','inspected',None,True)
    assert calls==[]
    initial_setup.gateway_deliveries(5)
    initial_setup.reconcile_gateway_delivery(row,'retry','inspected',None,True)
    assert calls==[('stop',{}),('owner',{'gateway_action':'deliveries','after':5}),('stop',{}),
        ('owner',{'gateway_action':'reconcile-delivery','delivery_id':'a'*64,'attempt':1,'decision':'retry',
            'note':'inspected','receipt':None,'confirm_not_delivered':True})]


@pytest.mark.parametrize('gate',['administrator','user','incomplete-wizard'])
def test_graphical_runtime_start_cannot_bypass_firstboot_gates(monkeypatch,gate):
    from haos import owner
    monkeypatch.setattr(initial_setup.os,'geteuid',lambda:0)
    monkeypatch.setattr(initial_setup,'account_status',lambda:{'complete':gate!='administrator'})
    monkeypatch.setattr(initial_setup,'normal_user_ready',lambda:gate!='user')
    monkeypatch.setattr(initial_setup,'setup_in_progress',lambda:gate=='incomplete-wizard')
    calls=[];monkeypatch.setattr(owner,'runtime_action',lambda verb:calls.append(verb))
    with pytest.raises(PermissionError):initial_setup.resume_runtime()
    assert calls==[]


def test_completed_owner_runtime_start_uses_fixed_existing_owner_action(monkeypatch):
    from haos import owner
    monkeypatch.setattr(initial_setup.os,'geteuid',lambda:0)
    monkeypatch.setattr(initial_setup,'account_status',lambda:{'complete':True})
    monkeypatch.setattr(initial_setup,'normal_user_ready',lambda:True)
    monkeypatch.setattr(initial_setup,'setup_in_progress',lambda:False)
    calls=[];monkeypatch.setattr(owner,'runtime_action',lambda verb:calls.append(verb))
    assert initial_setup.resume_runtime()=={'started':True} and calls==['start']


def test_owner_runtime_action_uses_only_fixed_units_and_preserves_policy_start(monkeypatch):
    from haos import owner
    monkeypatch.setattr(owner.os,'geteuid',lambda:0)
    monkeypatch.setattr(owner,'Path',lambda value:SimpleNamespace(exists=lambda:value=='/etc/haos/provider.json'))
    calls=[];events=[]
    monkeypatch.setattr(owner.subprocess,'run',lambda args,**kwargs:calls.append((args,kwargs)))
    monkeypatch.setattr(owner,'audit',lambda kind,details:events.append((kind,details)))
    with pytest.raises(ValueError):owner.runtime_action('restart-anything')
    assert calls==[]
    owner.runtime_action('start')
    assert [args for args,_ in calls]==[
        ['/usr/bin/systemctl','start','haos-provider.socket'],
        ['/usr/bin/systemctl','start','haos-controller.service','haos-hermes.service','haos-policy.service'],
        ['/usr/bin/systemctl','start','haos-gateway.service']]
    assert all(options=={'check':True,'timeout':60} for _,options in calls)
    assert events==[('runtime.start',{})]
    monkeypatch.setattr(owner.os,'geteuid',lambda:1000)
    with pytest.raises(PermissionError):owner.runtime_action('start')


def test_initial_owner_requires_repeated_password_before_stopping_services(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    with pytest.raises(ValueError):
        initial_setup.create_initial_owner("separate", "first", "second")


def test_reject_unknown_region_and_provider_without_mutating_os(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    with pytest.raises(ValueError):
        initial_setup.configure_region("unsupported", "us")
    with pytest.raises(ValueError):
        initial_setup.configure_region("de_AT.UTF-8", "xx")
    with pytest.raises(ValueError):
        initial_setup.configure_provider("codex", "model")
    with pytest.raises(ValueError):
        initial_setup.configure_provider("openai", "gpt-4")
    with pytest.raises(ValueError):
        initial_setup.configure_provider("local", "m", "secret", "http://127.0.0.1:4000/v1")


def test_update_allowlist_is_applied_before_any_command(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    with pytest.raises(ValueError):
        initial_setup.configure_update("ghcr.io/bad/unsafe", True)
    with pytest.raises(ValueError):
        initial_setup.configure_update("dev", "yes")


def test_physical_owner_status_is_not_a_permission(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(initial_setup, "owners", lambda: [])
    monkeypatch.setattr(initial_setup, "recovery_pending", lambda: False)
    assert initial_setup.account_status() == {"owner": False, "recovery": False, "complete": False, "pending": False}


def test_gateway_owner_and_platform_validation(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 1000)
    with pytest.raises(PermissionError):
        initial_setup.configure_gateway("id", "telegram", "x" * 24)
    with pytest.raises(PermissionError):
        initial_setup.pair_gateway_sender("id", "bot", "sender", "chat", "personal")
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    with pytest.raises(ValueError):
        initial_setup.configure_gateway("id", "whatsapp", "x" * 24)
    with pytest.raises(ValueError):
        initial_setup.configure_gateway("id", "telegram", "short")
    with pytest.raises(ValueError):
        initial_setup.pair_gateway_sender("id", "bot", "sender", "chat", "personal", ("root",))


def test_recovery_pending_prevents_success_without_loading_raw_codes(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(initial_setup, "owners", lambda: [{"username": "owner", "uid": 1001}])
    monkeypatch.setattr(initial_setup, "enrolled_owner", lambda name: SimpleNamespace(pw_uid=1001))
    monkeypatch.setattr(initial_setup, "recovery_pending", lambda: True)
    from haos import owner_recovery
    monkeypatch.setattr(owner_recovery.RecoveryCodes, "__init__", lambda self: None)
    monkeypatch.setattr(owner_recovery.RecoveryCodes, "_load", lambda self: {"owners": {"1001": {"hashes": ["dummy"] * 10}}})
    assert initial_setup.account_status()["complete"] is False
    with pytest.raises(PermissionError):
        initial_setup.finalize()


def test_root_service_cannot_start_while_new_recovery_codes_unconfirmed(monkeypatch):
    from haos import owner_ready
    monkeypatch.setattr(owner_ready.os, "geteuid", lambda: 0)
    monkeypatch.setattr(initial_setup, "recovery_pending", lambda: True)
    with pytest.raises(PermissionError, match="not yet been confirmed"):
        owner_ready.main()



def test_initial_setup_requires_valid_private_completion_receipt(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from haos import initial_setup
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    root = tmp_path / "haos-owner"
    root.mkdir(mode=0o700)
    receipt = root / "graphical-setup.json"
    monkeypatch.setattr(initial_setup, "COMPLETE", receipt)
    assert initial_setup.setup_finished() is False
    # A forged or loose-mode receipt may never substitute for the owner flow.
    receipt.write_text(json.dumps({"version": 1, "completed": True}))
    receipt.chmod(0o644)
    with pytest.raises(PermissionError):
        initial_setup.setup_finished()
    receipt.chmod(0o600)
    # CI is unprivileged: model a real root-owned inode without relaxing
    # production validation of file type, mode, link count or symlinks.
    import stat
    from types import SimpleNamespace
    real_lstat = Path.lstat
    def fake_root_owned_lstat(self, *args, **kwargs):
        info = real_lstat(self, *args, **kwargs)
        if self == receipt:
            return SimpleNamespace(st_uid=0, st_mode=info.st_mode,
                                   st_nlink=info.st_nlink)
        return info
    monkeypatch.setattr(Path, "lstat", fake_root_owned_lstat)
    # Mock only the trusted JSON parser after verifying the inode; CI's
    # parent directory is not root-owned like a real /var/lib/haos-owner.
    monkeypatch.setattr(
        __import__("haos.sandbox", fromlist=["trusted_json"]), "trusted_json",
        lambda path: json.loads(Path(path).read_text()))
    with pytest.raises(PermissionError):
        receipt.write_text(json.dumps({"version": 1, "completed": False}))
        initial_setup.setup_finished()
    receipt.write_text(json.dumps({"version": 1, "completed": True}))
    assert initial_setup.setup_finished() is True
    receipt.unlink()
    receipt.symlink_to(root / "missing")
    with pytest.raises(PermissionError):
        initial_setup.setup_finished()


def test_finalize_requires_observer_name_even_after_tty2_enrollment(monkeypatch):
    from haos import initial_setup
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(initial_setup, "account_status", lambda: {
        "owner": True, "recovery": True, "complete": True, "pending": False})
    monkeypatch.setattr(initial_setup, "setup_in_progress", lambda: False)
    from haos import owner_ready, normal_profile
    monkeypatch.setattr(owner_ready, "main", lambda: None)
    monkeypatch.setattr(normal_profile, "mark_ready",
                        lambda: (_ for _ in ()).throw(PermissionError("missing display name")))
    with pytest.raises(PermissionError, match="missing display name"):
        initial_setup.finalize()


def test_graphical_gateway_pairing_retains_exact_scope_thread_and_selected_rights(monkeypatch):
    from copy import deepcopy
    from haos import gateway_setup, owner
    from haos.gateway import GatewayPolicy
    policy = {'version': 1, 'connectors': [{'id': 'discord-main', 'platform': 'discord'}], 'bindings': []}
    saved, actions = [], []
    monkeypatch.setattr(initial_setup.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(gateway_setup, 'load', lambda: (deepcopy(policy), {'connectors': {}}))
    monkeypatch.setattr(gateway_setup, 'persist', lambda value, credentials: saved.append(value))
    monkeypatch.setattr(initial_setup, 'quiesce_for_setup', lambda **kwargs: actions.append(kwargs))
    monkeypatch.setattr(owner, 'audit', lambda *args: None)
    initial_setup.pair_gateway_sender('owner-chat', 'discord-main', 'sender-1', 'channel-1', 'personal',
        ('create', 'read', 'answer'), scope='guild-1', thread='thread-1')
    assert actions == [{'gateway_only': True}] and len(saved) == 1
    configured = GatewayPolicy(saved[0])
    envelope = {'platform': 'discord', 'sender': 'sender-1', 'chat': 'channel-1', 'scope': 'guild-1',
        'thread': 'thread-1', 'message_id': 'fixture-message', 'is_bot': False, 'text': 'fixture'}
    assert configured.authorize('discord-main', envelope)['capabilities'] == ['create', 'read', 'answer']
    for key, value in [('sender', 'other'), ('chat', 'other'), ('scope', ''), ('thread', ''), ('scope', 'other'), ('thread', 'other')]:
        with pytest.raises(PermissionError):
            configured.authorize('discord-main', {**envelope, key: value})
    actions.clear(); saved.clear()
    with pytest.raises(ValueError):
        initial_setup.pair_gateway_sender('invalid', 'discord-main', 'sender-1', 'channel-1', 'personal', scope='bad\nscope')
    assert not actions and not saved


def test_gateway_management_exposes_metadata_and_rejects_unknown_selection_before_stopping(monkeypatch):
    from haos import gateway_setup
    policy = {'version': 1, 'connectors': [{'id': 'bot', 'platform': 'telegram'}], 'bindings': []}
    actions = []
    monkeypatch.setattr(initial_setup.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(gateway_setup, 'load', lambda: (policy, {'connectors': {'bot': {'token': 'private-fixture-token'}}}))
    monkeypatch.setattr(initial_setup, 'quiesce_for_setup', lambda **kwargs: actions.append(('stop', kwargs)))
    monkeypatch.setattr(gateway_setup, 'owner_gateway', lambda args: actions.append((args.gateway_action, getattr(args, 'connector', None))))
    assert initial_setup.gateway_configuration() == {'connectors': policy['connectors'], 'bindings': []}
    assert 'private-fixture-token' not in repr(initial_setup.gateway_configuration())
    for action, selected in [('setup', ''), ('revoke', 'missing'), ('remove', 'missing'), ('start', 'bot')]:
        with pytest.raises(ValueError):
            initial_setup.manage_gateway(action, selected)
    assert not actions
    initial_setup.manage_gateway('start')
    initial_setup.manage_gateway('remove', 'bot')
    assert actions == [('start', None), ('stop', {'gateway_only': True}), ('remove', 'bot')]


def test_gateway_process_status_uses_only_fixed_service_and_public_fields(monkeypatch):
    calls = []
    monkeypatch.setattr(initial_setup.os, 'geteuid', lambda: 0)
    def status(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout='LoadState=loaded\nActiveState=active\nSubState=running\nResult=success\nExecMainStatus=0\n')
    monkeypatch.setattr(initial_setup.subprocess, 'run', status)
    assert initial_setup.gateway_process_status()['ActiveState'] == 'active'
    assert calls == [['/usr/bin/systemctl', 'show', '--property=LoadState,ActiveState,SubState,Result,ExecMainStatus', 'haos-gateway.service']]
