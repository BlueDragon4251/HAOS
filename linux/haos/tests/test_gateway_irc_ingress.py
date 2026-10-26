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
    script='import sys;sys.path.insert(0,'+repr(str(source))+');import haos.gateway_irc_ingress;assert "gateway.config" not in sys.modules'
    result=subprocess.run([sys.executable,'-I','-S','-c',script],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
