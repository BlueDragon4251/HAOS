"""Prepared HA admission stays closed and imports without optional runtime SDKs."""
from pathlib import Path
import subprocess
import sys

import pytest

from haos.gateway import GatewayPolicy
from haos.gateway_homeassistant_ingress import PreparedHomeAssistantPolicy


def config():
    return {'version':1,'connectors':[{'id':'ha','platform':'homeassistant'}],'bindings':[{
        'id':'owner','connector':'ha','sender':'a'*32,'chat':'light.owner','scope':'','thread':'',
        'identity':'owner','capabilities':['create','read'],'generation':'b'*64,'since':1}]}


def test_prepared_homeassistant_does_not_enable_public_setup():
    with pytest.raises(ValueError):GatewayPolicy(config())
    assert PreparedHomeAssistantPolicy(config()).bindings['owner']['chat']=='light.owner'


@pytest.mark.parametrize('change',[{'sender':'homeassistant'},{'sender':'system'},{'chat':'light.*'},
    {'scope':'unapproved'},{'thread':'unapproved'},{'since':False}])
def test_prepared_homeassistant_requires_exact_authenticated_actor_entity_and_grant(change):
    value=config();value['bindings'][0].update(change)
    with pytest.raises(ValueError):PreparedHomeAssistantPolicy(value)


def test_homeassistant_ingress_imports_without_site_packages_or_upstream():
    source=Path(__file__).resolve().parents[1]
    script=('import sys; sys.path.insert(0,'+repr(str(source))+'); '
        'import haos.gateway_homeassistant_ingress, haos.gateway_homeassistant_transport, haos.gateway_homeassistant_delivery; '
        'assert "gateway.config" not in sys.modules; assert "plugins" not in sys.modules')
    child=subprocess.run([sys.executable,'-I','-S','-c',script],capture_output=True,text=True)
    assert child.returncode==0,child.stderr


@pytest.mark.parametrize('value',[1,'true',[],{}])
def test_prepared_homeassistant_shared_audience_approval_cannot_use_truthy_non_boolean(value):
    source=config();source['bindings'][0]['homeassistant_shared_notifications']=value
    with pytest.raises(ValueError):PreparedHomeAssistantPolicy(source)
