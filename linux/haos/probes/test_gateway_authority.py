"""Actual owner-protected files in root-owned disposable directories, never host config."""

import copy
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from haos.gateway_setup import load, persist


def test_owner_credentials_and_pairing_are_persisted_with_separate_modes(tmp_path):
    assert os.geteuid() == 0, "run this explicit root-authority fixture as root"
    policy = {"version": 1, "connectors": [{"id": "first", "platform": "telegram"}], "bindings": []}
    credentials = {"connectors": {"first": {"token": "disposable-fixture-credential"}}}
    persist(policy, credentials, config=tmp_path, gid=0)
    policy_path = tmp_path / "gateways.json"
    secret_path = tmp_path / "gateway-credentials"
    assert stat.S_IMODE(policy_path.stat().st_mode) == 0o640
    assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600
    assert secret_path.stat().st_uid == 0
    assert "disposable-fixture-credential" not in policy_path.read_text()
    assert load(tmp_path) == (policy, credentials)


@pytest.mark.parametrize("attack", ["writable-directory", "symlink-directory", "symlink-policy", "symlink-secret", "writable-policy", "foreign-secret"])
def test_unsafe_authority_files_are_refused_without_overwriting_them(tmp_path, attack):
    assert os.geteuid() == 0
    config = tmp_path / "configuration"
    config.mkdir(mode=0o700)
    policy = {"version": 1, "connectors": [{"id": "first", "platform": "telegram"}], "bindings": []}
    credentials = {"connectors": {"first": {"token": "disposable-fixture-credential"}}}
    persist(policy, credentials, config=config, gid=0)
    if attack == "writable-directory":
        config.chmod(0o777)
    elif attack == "symlink-directory":
        link = tmp_path / "symlink-config"
        link.symlink_to(config)
        config = link
    elif attack.startswith("symlink-"):
        path = config / ("gateways.json" if attack == "symlink-policy" else "gateway-credentials")
        target = config / "unchanged-neighbor"
        path.rename(target)
        path.symlink_to(target)
    elif attack == "writable-policy":
        (config / "gateways.json").chmod(0o666)
    else:
        os.chown(config / "gateway-credentials", 65534, 65534)
    before = (config / "gateway-credentials").read_bytes()
    with pytest.raises(PermissionError):
        persist(policy, copy.deepcopy(credentials), config=config, gid=0)
    assert (config / "gateway-credentials").read_bytes() == before


def test_graphical_gateway_management_keeps_real_root_files_and_denies_another_uid(tmp_path, monkeypatch):
    """Real UID/files; service lifecycle and audit are separate disposable CI checks."""
    from haos import initial_setup, gateway_setup, owner
    from haos.gateway import GatewayPolicy
    assert os.geteuid() == 0
    config = tmp_path / 'configuration'
    config.mkdir(mode=0o700)
    value = {'version': 1, 'connectors': [{'id': 'discord-main', 'platform': 'discord'}], 'bindings': []}
    credentials = {'connectors': {'discord-main': {'token': 'disposable-gateway-fixture-credential'}}}
    persist(value, credentials, config=config, gid=0)
    original_load, original_persist = gateway_setup.load, gateway_setup.persist
    monkeypatch.setattr(gateway_setup, 'load', lambda *args: original_load(config))
    monkeypatch.setattr(gateway_setup, 'persist', lambda policy, secret: original_persist(policy, secret, config=config, gid=0))
    monkeypatch.setattr(initial_setup, 'quiesce_for_setup', lambda **kwargs: None)
    monkeypatch.setattr(gateway_setup, 'stopped_gateway', lambda: None)
    audit = []
    monkeypatch.setattr(owner, 'audit', lambda action, fields: audit.append(action))
    pid = os.fork()
    if pid == 0:
        try:
            os.setgroups([]); os.setgid(65534); os.setuid(65534)
            for action in (initial_setup.gateway_configuration, lambda: initial_setup.manage_gateway('remove', 'discord-main')):
                try:
                    action()
                except PermissionError:
                    continue
                raise AssertionError('unprivileged graphical gateway administration accepted')
            os._exit(0)
        except BaseException:
            os._exit(3)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    initial_setup.pair_gateway_sender('paired', 'discord-main', 'sender', 'channel', 'principal',
        ('create', 'read', 'answer'), scope='guild', thread='thread')
    policy, secret = original_load(config)
    assert policy['bindings'][0]['scope'] == 'guild' and policy['bindings'][0]['thread'] == 'thread'
    assert policy['bindings'][0]['capabilities'] == ['create', 'read', 'answer']
    assert secret == credentials
    assert 'disposable-gateway-fixture-credential' not in repr(initial_setup.gateway_configuration())
    initial_setup.manage_gateway('revoke', 'paired')
    policy, secret = original_load(config)
    assert not GatewayPolicy(policy).bindings and secret == credentials
    initial_setup.manage_gateway('remove', 'discord-main')
    policy, secret = original_load(config)
    assert not policy['connectors'] and secret == {'connectors': {}}
    assert audit == ['setup.gateway-pair', 'gateway.revoke', 'gateway.remove']
    for name, expected_mode in [('gateways.json', 0o640), ('gateway-credentials', 0o600)]:
        assert (config / name).stat().st_uid == 0
        assert stat.S_IMODE((config / name).stat().st_mode) == expected_mode
        assert 'disposable-gateway-fixture-credential' not in (config / name).read_text()


def test_real_owner_publication_renews_pairing_epochs_and_preserves_unchanged_grants(tmp_path):
    from haos.gateway import GatewayPolicy, digest
    assert os.geteuid() == 0, 'actual owner UID/files required'
    policy = {'version': 1, 'connectors': [{'id': 'first', 'platform': 'telegram'}], 'bindings': [
        {'id': 'paired', 'connector': 'first', 'sender': '42', 'chat': '42', 'scope': '', 'thread': '',
         'identity': 'principal', 'capabilities': ['create', 'read']}]}
    secret = {'connectors': {'first': {'token': 'disposable-epoch-fixture-credential'}}}
    persist(policy, secret, config=tmp_path, gid=0)
    first, _ = load(tmp_path)
    epoch = first['bindings'][0]['generation']
    persist(first, secret, config=tmp_path, gid=0)
    assert load(tmp_path)[0] == first
    changed = copy.deepcopy(first); changed['bindings'][0]['capabilities'] = ['create']
    persist(changed, secret, config=tmp_path, gid=0)
    edited, _ = load(tmp_path)
    assert edited['bindings'][0]['generation'] != epoch
    persist(first, secret, config=tmp_path, gid=0)
    reversed_policy, _ = load(tmp_path)
    assert reversed_policy['bindings'][0]['generation'] not in {epoch, edited['bindings'][0]['generation']}
    persist({**first, 'bindings': []}, secret, config=tmp_path, gid=0)
    persist(first, secret, config=tmp_path, gid=0)
    repaired, stored_secret = load(tmp_path)
    assert stored_secret == secret
    assert repaired['bindings'][0]['generation'] not in {
        epoch, edited['bindings'][0]['generation'], reversed_policy['bindings'][0]['generation']}
    with pytest.raises(PermissionError):
        GatewayPolicy(repaired).current_binding({'binding_id': 'paired', 'binding_digest': digest(first['bindings'][0])})
    assert 'generation' not in policy['bindings'][0]


@pytest.mark.parametrize('interrupted_after', ['journal', 'withdrawal', 'credentials', 'policy'])
@pytest.mark.parametrize('credential_field',['token','app_token'])
def test_real_gateway_rotation_recovers_after_every_durable_stage_without_old_sender_authority(tmp_path, monkeypatch, interrupted_after,credential_field):
    from haos import gateway_publication
    assert os.geteuid() == 0, 'actual protected files and owner UID required'
    policy = {'version': 1, 'connectors': [{'id': 'first', 'platform': 'telegram'}], 'bindings': [
        {'id': 'paired', 'connector': 'first', 'sender': '42', 'chat': '42', 'scope': '', 'thread': '',
         'identity': 'principal', 'capabilities': ['create', 'read']}]}
    old_secret = {'connectors': {'first': {'token': 'disposable-old-account-credential'}}}
    if credential_field=='app_token':
        policy['connectors'][0]['platform']='slack'
        policy['bindings'][0].update(sender='U42',chat='C123',scope='T999')
        old_secret['connectors']['first']={'token':'xoxb-'+'x'*24,'app_token':'xapp-'+'y'*24}
    persist(policy, old_secret, config=tmp_path, gid=0)
    before, _ = load(tmp_path)
    new_secret=copy.deepcopy(old_secret)
    new_secret['connectors']['first'][credential_field]='xapp-'+'z'*24 if credential_field=='app_token' else 'disposable-new-account-credential'
    original = gateway_publication.atomic_json
    writes = []
    class PowerLoss(Exception): pass
    def durable_then_interrupt(path, value, **kwargs):
        original(path, value, **kwargs)
        stage = ('journal' if path.name == gateway_publication.PENDING else 'credentials'
            if path.name == 'gateway-credentials' else 'policy' if value['connectors'] else 'withdrawal')
        writes.append(stage)
        if stage == interrupted_after: raise PowerLoss()
    monkeypatch.setattr(gateway_publication, 'atomic_json', durable_then_interrupt)
    with pytest.raises(PowerLoss): persist(before, new_secret, config=tmp_path, gid=0)
    assert gateway_publication.pending(tmp_path)
    with pytest.raises(PermissionError): load(tmp_path)
    from haos.sandbox import trusted_json
    journal = trusted_json(tmp_path/gateway_publication.PENDING)
    assert journal['previous_policy'] == before
    assert journal['policy']['bindings'] == []
    assert stat.S_IMODE((tmp_path/gateway_publication.PENDING).stat().st_mode) == 0o600
    monkeypatch.setattr(gateway_publication, 'atomic_json', original)
    assert gateway_publication.recover(tmp_path, 0)['recovered'] is True
    assert not gateway_publication.pending(tmp_path)
    after, secret = load(tmp_path)
    assert after['connectors'] == before['connectors'] and after['bindings'] == []
    assert secret == new_secret
    public = trusted_json(tmp_path/'gateways.json')
    private = trusted_json(tmp_path/'gateway-credentials')
    gateway_publication.validate_snapshot(public, private)
    assert public['publication'] == private['publication']
    assert all(secret_value not in (tmp_path/'gateways.json').read_text()
        for account in (old_secret['connectors']['first'],new_secret['connectors']['first']) for secret_value in account.values())
    with pytest.raises(FileNotFoundError): gateway_publication.recover(tmp_path, 0)
