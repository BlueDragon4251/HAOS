"""Private ntfy policy/config must remain usable without optional Hermes imports."""
from pathlib import Path
import subprocess
import sys

import pytest

from haos.gateway_ntfy_profile import credentials


def test_private_gateway_modules_import_with_no_site_packages_or_upstream():
    source = Path(__file__).resolve().parents[1]
    script = ('import sys; sys.path.insert(0,'+repr(str(source))+'); '
              'import haos.gateway_ntfy_profile, haos.gateway_ntfy_delivery, haos.gateway_ntfy_transport; '
              'assert "gateway.config" not in sys.modules; assert "plugins" not in sys.modules')
    result = subprocess.run([sys.executable,'-I','-S','-c',script],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('change', [
    {'token':''}, {'token':'newline\ncredential'}, {'token':'nul\0credential'},
    {'topic':'*'}, {'topic':'../neighbor'}, {'topic':'one/two'},
    {'server_url':'http://unsafe.invalid'}, {'server_url':'https://user:pass@host.invalid'},
    {'server_url':'https://host.invalid/%2fescape'}, {'server_url':'https://host.invalid/path/../escape'},
    {'extra':{'auto_authorize':True}},
])
def test_private_ntfy_configuration_refuses_ambiguous_or_unapproved_inputs(change):
    value={'token':'local-only-credential','topic':'private-topic','server_url':'https://owner.invalid'}
    with pytest.raises(ValueError):
        credentials({**value,**change})


def ntfy_policy():
    return {'version':1,'connectors':[{'id':'topic','platform':'ntfy'}],'bindings':[{
        'id':'owner','connector':'topic','sender':'private','chat':'private','scope':'','thread':'',
        'identity':'topic-owner','capabilities':['create','read'],'trust_topic_publishers':True}]}


def test_public_ntfy_snapshot_cannot_redirect_grant_to_another_credential_topic():
    from haos.gateway_publication import validate_snapshot
    policy=ntfy_policy()
    value={'connectors':{'topic':{'token':'u:p','server_url':'https://owner.invalid','topic':'private'}}}
    validate_snapshot(policy,value)
    value['connectors']['topic']['topic']='another'
    with pytest.raises(ValueError):validate_snapshot(policy,value)


def test_legacy_ntfy_grant_without_publication_epoch_cannot_capture_original(tmp_path):
    from types import SimpleNamespace
    import time
    from haos.gateway import GatewayPolicy
    from haos.gateway_ntfy import capture,snapshot
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    current=lambda:GatewayPolicy(ntfy_policy())
    inbox=NativeInbox(tmp_path/'native.db',Redactor())
    adapter=SimpleNamespace(_topic='private',_haos_native=SimpleNamespace(policy=current,connector='topic',inbox=inbox))
    event={'event':'message','topic':'private','id':'valid-id','time':int(time.time()),'message':'no legacy replay'}
    try:
        with pytest.raises(PermissionError):capture(adapter,event,snapshot(current(),'topic'))
        assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==0
    finally:inbox.close()


def test_ntfy_factory_cannot_bypass_private_profile_context():
    from haos.gateway_runtime import build_adapter
    with pytest.raises(ValueError):build_adapter('ntfy',{'token':'u:p','server_url':'https://owner.invalid','topic':'private'})


@pytest.mark.parametrize('private', ['owner:päss with spaces','owner:password:colon'])
def test_ntfy_native_basic_credentials_preserve_utf8_password_spaces_and_colons(private):
    value={'token':private,'topic':'private-topic','server_url':'https://owner.invalid'}
    assert credentials(value)==value


def test_native_basic_wire_alias_is_redacted_before_gateway_logs_or_admission():
    import base64
    from haos.gateway import GatewayPolicy
    from haos.gateway_runtime import credential_redactor
    private='owner:päss with spaces'
    encoded=base64.b64encode(private.encode('utf-8')).decode('ascii')
    redactor=credential_redactor({'connectors':{'topic':{'token':private}}},GatewayPolicy(ntfy_policy()))
    assert redactor.text('raw '+private+' encoded '+encoded)=='raw [REDACTED] encoded [REDACTED]'
