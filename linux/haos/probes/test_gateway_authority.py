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
@pytest.mark.parametrize('credential_field',['token','app_token','server_url'])
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
    if credential_field=='server_url':
        policy['connectors'][0]['platform']='mattermost'
        policy['bindings'][0].update(sender='u'*26,chat='c'*26,scope='s'*26)
        old_secret['connectors']['first']={'token':'x'*26,'server_url':'https://old-owner.invalid'}
    persist(policy, old_secret, config=tmp_path, gid=0)
    before, _ = load(tmp_path)
    new_secret=copy.deepcopy(old_secret)
    new_secret['connectors']['first'][credential_field]='xapp-'+'z'*24 if credential_field=='app_token' else 'https://new-owner.invalid' if credential_field=='server_url' else 'disposable-new-account-credential'
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


def test_matrix_identity_cannot_be_published_with_incomplete_private_credentials(tmp_path):
    from haos.gateway_matrix_policy import PreparedMatrixPolicy
    assert os.geteuid()==0,'actual owner files and root authority required'
    policy={'version':1,'connectors':[{'id':'matrix-preview','platform':'matrix'}],'bindings':[]}
    assert PreparedMatrixPolicy(policy).connectors['matrix-preview']['platform']=='matrix'
    before={path.name for path in tmp_path.iterdir()}
    with pytest.raises(ValueError):
        persist(policy,{'connectors':{'matrix-preview':{'token':'disposable-preview-token'}}},config=tmp_path,gid=0)
    assert not (tmp_path/'gateways.json').exists()
    assert not (tmp_path/'gateway-credentials').exists()
    assert not (tmp_path/'gateway-publication.json').exists()
    assert {path.name for path in tmp_path.iterdir()}<=before|{'.gateway-publication.lock'}


def test_graphical_matrix_owner_publication_devices_rotation_and_real_uid_denial(tmp_path,monkeypatch):
    import base64
    from haos import initial_setup,gateway_setup,owner
    assert os.geteuid()==0,'real owner files and UID gates required'
    config=tmp_path/'config';config.mkdir(mode=0o700)
    original_load,original_persist=gateway_setup.load,gateway_setup.persist
    monkeypatch.setattr(gateway_setup,'load',lambda *args:original_load(config))
    monkeypatch.setattr(gateway_setup,'persist',lambda policy,secret:original_persist(policy,secret,config=config,gid=0))
    monkeypatch.setattr(initial_setup,'quiesce_for_setup',lambda **kwargs:None)
    actions=[];monkeypatch.setattr(owner,'audit',lambda action,fields:actions.append(action))
    fields={'homeserver':'https://matrix.example.org','user_id':'@haos:example.org','device_id':'HAOS'}
    child=os.fork()
    if child==0:
        try:
            os.setgroups([]);os.setgid(65534);os.setuid(65534)
            for action in (lambda:initial_setup.configure_gateway('matrix-main','matrix','disposable-private-matrix-token',**fields),
                    lambda:initial_setup.matrix_gateway_devices('matrix-main','@owner:example.org')):
                try:action()
                except PermissionError:continue
                os._exit(4)
            os._exit(0)
        except BaseException:os._exit(3)
    assert os.waitstatus_to_exitcode(os.waitpid(child,0)[1])==0
    initial_setup.configure_gateway('matrix-main','matrix','disposable-private-matrix-token',
        recovery_key='disposable-private-recovery-fixture',**fields)
    key=base64.b64encode(b'x'*32).decode().rstrip('=')
    initial_setup.pair_gateway_sender('phone','matrix-main','@owner:example.org','!room:example.org','principal',
        ('create','read'),matrix_devices=[{'device_id':'PHONE','ed25519':key,'curve25519':key}],
        allow_plaintext=False,require_mention=True)
    policy,secret=original_load(config)
    binding=policy['bindings'][0]
    assert binding['matrix_devices'][0]['device_id']=='PHONE' and not binding['allow_plaintext']
    assert binding['generation'] and binding['since']>0 and binding['require_mention'] is True
    public=initial_setup.gateway_configuration()
    assert 'disposable-private-matrix-token' not in repr(public) and 'disposable-private-recovery-fixture' not in repr(public)
    assert stat.S_IMODE((config/'gateway-credentials').stat().st_mode)==0o600
    assert stat.S_IMODE((config/'gateways.json').stat().st_mode)==0o640
    assert secret['connectors']['matrix-main']['homeserver']==fields['homeserver']
    preserved=config/'owner-recovery-canary';preserved.write_bytes(b'disposable recovery evidence');preserved.chmod(0o600)
    initial_setup.configure_gateway('matrix-main','matrix','disposable-rotated-matrix-token',**fields)
    policy,secret=original_load(config)
    assert policy['bindings']==[] and secret['connectors']['matrix-main']['token']=='disposable-rotated-matrix-token'
    assert preserved.read_bytes()==b'disposable recovery evidence'
    assert 'setup.gateway-pair' in actions


def test_matrix_account_helper_refuses_to_run_credentialed_sdk_as_root():
    from haos.gateway_matrix_account import main
    assert os.geteuid()==0,'actual root identity required'
    with pytest.raises(PermissionError):main()


def test_matrix_profile_kernel_lease_is_private_exclusive_and_released_between_real_uids():
    import select
    import tempfile
    from haos.gateway_matrix_profile import acquire_lease
    assert os.geteuid()==0,'actual kernel identities required'
    with tempfile.TemporaryDirectory(prefix='haos-matrix-lease-') as temporary:
        root=Path(temporary);root.chmod(0o755)
        profile=root/'profile';profile.mkdir(mode=0o700);os.chown(profile,65534,65534)
        canary=root/'owner-canary';canary.write_text('disposable root-only owner evidence');canary.chmod(0o600)
        ready_read,ready_write=os.pipe();release_read,release_write=os.pipe()
        first=os.fork()
        if first==0:
            try:
                os.close(ready_read);os.close(release_write)
                os.setgroups([]);os.setgid(65534);os.setuid(65534)
                fd=acquire_lease(profile)
                try:canary.read_text()
                except PermissionError:pass
                else:os._exit(4)
                os.write(ready_write,b'1')
                assert os.read(release_read,1)==b'1'
                os.close(fd);os._exit(0)
            except BaseException:os._exit(3)
        os.close(ready_write);os.close(release_read)
        def other(uid,allowed):
            child=os.fork()
            if child==0:
                try:
                    os.setgroups([]);os.setgid(uid);os.setuid(uid)
                    if uid==65533:
                        try:(profile/'profile.lock').read_bytes()
                        except PermissionError:pass
                        else:os._exit(7)
                    try:fd=acquire_lease(profile)
                    except PermissionError:
                        if allowed:os._exit(5)
                    else:
                        os.close(fd)
                        if not allowed:os._exit(6)
                    try:canary.read_text()
                    except PermissionError:pass
                    else:os._exit(4)
                    os._exit(0)
                except BaseException:os._exit(3)
            assert os.waitstatus_to_exitcode(os.waitpid(child,0)[1])==0
        try:
            assert select.select([ready_read],[],[],5)[0] and os.read(ready_read,1)==b'1'
            assert (profile/'profile.lock').stat().st_uid==65534
            assert stat.S_IMODE((profile/'profile.lock').stat().st_mode)==0o600
            other(65533,False);other(65534,False)
        finally:
            try:os.write(release_write,b'1')
            except BrokenPipeError:pass
            os.close(release_write);os.close(ready_read)
            assert os.waitstatus_to_exitcode(os.waitpid(first,0)[1])==0
        other(65534,True)
        assert canary.read_text()=='disposable root-only owner evidence'


# Actual cross-UID installation from restrictive public build input.
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

spec = importlib.util.spec_from_file_location('install_package', Path(__file__).parents[1] / 'runtime/install_package.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def public_build_directory():
    with tempfile.TemporaryDirectory(prefix='haos-public-build-') as directory:
        yield Path(directory)


def test_restrictive_source_installs_readable_code_without_exposing_neighbor(public_build_directory):
    tmp_path = public_build_directory
    assert os.geteuid() == 0
    tmp_path.chmod(0o755)
    source = tmp_path / 'source'
    source.mkdir(mode=0o700)
    (source / '__init__.py').write_text('answer = 42\n')
    (source / '__init__.py').chmod(0o600)
    secret = tmp_path / 'private-credential'
    secret.write_text('disposable-private-value')
    secret.chmod(0o600)
    destination = tmp_path / 'package'
    installer.install_package(source, destination)
    assert destination.stat().st_mode & 0o777 == 0o755
    assert (destination / '__init__.py').stat().st_mode & 0o777 == 0o644
    assert secret.stat().st_mode & 0o777 == 0o600
    result = subprocess.run([sys.executable, '-I', '-c',
        'import runpy,sys; assert runpy.run_path(sys.argv[1])["answer"] == 42',
        str(destination / '__init__.py')], user=65534, group=65534, extra_groups=[], capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('attack', ['source-link', 'destination-link', 'destination-hardlink'])
def test_installation_refuses_links_without_modifying_neighbor(tmp_path, attack):
    assert os.geteuid() == 0
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'module.py').write_text('public code')
    neighbor = tmp_path / 'private'
    neighbor.write_text('unchanged')
    neighbor.chmod(0o600)
    destination = tmp_path / 'package'
    destination.mkdir()
    if attack == 'source-link':
        (source / 'link').symlink_to(neighbor)
    elif attack == 'destination-link':
        (destination / 'module.py').symlink_to(neighbor)
    else:
        os.link(neighbor, destination / 'module.py')
    with pytest.raises(ValueError):
        installer.install_package(source, destination)
    assert neighbor.read_text() == 'unchanged'
    assert neighbor.stat().st_mode & 0o777 == 0o600


def test_actual_ntfy_owner_publication_and_cross_uid_credential_isolation(public_build_directory):
    from haos.gateway import GatewayPolicy
    assert os.geteuid() == 0
    config = public_build_directory
    config.chmod(0o755)
    policy = {'version':1,'connectors':[{'id':'topic','platform':'ntfy'}],'bindings':[]}
    secret = {'connectors':{'topic':{'token':'u:p','server_url':'https://owner.invalid','topic':'private-topic'}}}
    persist(policy, secret, config=config, gid=65534)
    policy, stored = load(config)
    assert stored == secret
    policy['bindings'] = [{'id':'owner','connector':'topic','sender':'private-topic','chat':'private-topic',
        'scope':'','thread':'','identity':'owner','capabilities':['create','read'],'trust_topic_publishers':True}]
    persist(policy, secret, config=config, gid=65534)
    published, stored = load(config)
    grant = published['bindings'][0]
    assert len(grant['generation']) == 64 and type(grant['since']) is int and grant['since'] > 0
    source={'platform':'ntfy','sender':'private-topic','chat':'private-topic','scope':'','thread':'',
        'message_id':'real-shape-id','is_bot':False,'text':'fixture'}
    assert GatewayPolicy(published).authorize('topic',source) == grant
    with pytest.raises(PermissionError):
        GatewayPolicy(published).authorize('topic',{**source,'sender':'pretend-owner'})
    script = ('from pathlib import Path; import sys; '
              'assert Path(sys.argv[1]).read_bytes(); '
              '\ntry: Path(sys.argv[2]).read_bytes()\nexcept PermissionError: pass\nelse: raise AssertionError("private credential became readable")')
    child = subprocess.run([sys.executable,'-I','-c',script,str(config/'gateways.json'),str(config/'gateway-credentials')],
        user=65534,group=65534,extra_groups=[],capture_output=True)
    assert child.returncode == 0, child.stderr
    assert stat.S_IMODE((config/'gateway-credentials').stat().st_mode) == 0o600
    # An explicit credential edit withdraws old grants before publishing, while
    # retaining the store and neighboring owner data.
    marker = config/'retained-owner-data'
    marker.write_text('preserved')
    replacement={'connectors':{'topic':{**secret['connectors']['topic'],'token':'rotated-private-credential'}}}
    persist(published,replacement,config=config,gid=65534)
    assert load(config)[0]['bindings'] == [] and marker.read_text() == 'preserved'
    assert 'u:p' not in (config/'gateways.json').read_text()
