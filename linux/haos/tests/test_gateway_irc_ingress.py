"""Prepared account-bound IRC admission imports without optional runtime packages."""
from pathlib import Path
import subprocess
import sys

import pytest

from haos.gateway import GatewayPolicy
from haos.gateway_irc_ingress import PreparedIRCPolicy


def config():
    return {'version':1,'connectors':[{'id':'irc','platform':'irc'}],'bindings':[{
        'id':'owner','connector':'irc','sender':'owner-account','chat':'#haos',
        'scope':'irc.fixture.invalid:6697','thread':'','identity':'owner',
        'capabilities':['create','read'],'generation':'a'*64,'since':1}]}


def test_irc_stays_unavailable_in_public_policy_until_transport_and_owner_setup_exist():
    with pytest.raises(ValueError):GatewayPolicy(config())
    assert PreparedIRCPolicy(config()).bindings['owner']['sender']=='owner-account'


@pytest.mark.parametrize('change',[{'sender':'*'},{'sender':'Nick!user@host'},
    {'chat':'#*'},{'chat':'nickname'},{'scope':''},{'scope':'irc.fixture.invalid'},
    {'thread':'unreviewed'},{'since':False},{'generation':''}])
def test_irc_prepared_owner_routes_are_exact_accounts_not_nick_or_hostmask(change):
    value=config();value['bindings'][0].update(change)
    with pytest.raises(ValueError):PreparedIRCPolicy(value)


def test_irc_boundary_imports_without_hermes_or_site_packages():
    source=Path(__file__).resolve().parents[1]
    script='import sys;sys.path.insert(0,'+repr(str(source))+');import haos.gateway_irc_ingress,haos.gateway_irc_transport,haos.gateway_irc_profile;assert "gateway.config" not in sys.modules'
    result=subprocess.run([sys.executable,'-I','-S','-c',script],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('change',[{'server':'IRC.fixture.invalid'},{'server':'user@irc.fixture.invalid'},
    {'server':'irc..invalid'},{'port':True},{'port':0},{'port':65536},
    {'nickname':'bot\nPRIVMSG'},{'nickname':'#channel'},{'channel':'#*'},
    {'server_password':'secret\r\nPRIVMSG #other :inject'},
    {'nickserv_password':'private-fixture'},{'use_tls':False}])
def test_private_irc_credentials_refuse_protocol_injection_and_unreviewed_auth(change):
    from haos.gateway_irc_transport import credentials
    with pytest.raises(ValueError):credentials({'server':'irc.fixture.invalid','port':6697,
        'nickname':'haos-bot','channel':'#haos',**change})


@pytest.mark.parametrize('options',[{'sasl_username':'bot-account'}, {'sasl_password':'private-fixture'},
    {'sasl_username':True,'sasl_password':'private-fixture'},
    {'sasl_username':'*','sasl_password':'private-fixture'},
    {'sasl_username':'bot-account','sasl_password':False},
    {'sasl_username':'bot-account','sasl_password':'private\0fixture'},
    {'sasl_username':'bot-account','sasl_password':'private\r\nfixture'},
    {'sasl_username':'bot-account','sasl_password':'x'*4097},
    {'sasl_username':'bot-account','sasl_password':'😀'*1025}])
def test_private_irc_sasl_requires_paired_bounded_account_credentials(options):
    from haos.gateway_irc_transport import credentials
    with pytest.raises(ValueError):credentials({'server':'irc.fixture.invalid','port':6697,
        'nickname':'haos-bot','channel':'#haos',**options})


@pytest.mark.parametrize('kind',['public','symlink','relative'])
def test_prepared_irc_profile_refuses_untrusted_parent_before_optional_runtime_import(tmp_path,kind):
    from haos.gateway_irc_profile import build
    value={'server':'irc.fixture.invalid','port':6697,'nickname':'haos-bot','channel':'#haos'}
    parent=tmp_path/'private';parent.mkdir(mode=0o700)
    if kind=='public':parent.chmod(0o755)
    if kind=='symlink':
        link=tmp_path/'alias';link.symlink_to(parent,target_is_directory=True);parent=link
    if kind=='relative':parent=Path('relative-untrusted-parent')
    with pytest.raises((ValueError,PermissionError)):
        build(value,parent,'irc',lambda:PreparedIRCPolicy(config()),None)
    assert not (tmp_path/'private/profile.lock').exists()
