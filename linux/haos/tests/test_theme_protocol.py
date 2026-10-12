import uuid

import pytest

from haos.theme_protocol import COLORS,SDK,action,receipt
from haos.gui import GuiBroker
from haos.store import MissionStore


def spec():return {'colors':{k:'#123456' for k in COLORS},'label':'Dark glass','shell':{'theme':'ocean','scheme':'dark'}}


def test_theme_authoring_is_complete_data_in_the_existing_schema():
    assert action({'operation':'theme.sdk'})=={'operation':'theme.sdk'}
    assert action({'operation':'theme.stage','theme':spec()})['theme']==spec()
    assert receipt('theme.sdk',SDK)==SDK


@pytest.mark.parametrize('field,value',[('name','owner-theme'),('wallpaper','/etc/haos/secret'),('plugins',['root']),
    ('script','owner()'),('gtk',{'command':'root'}),('colors',{'bg':'url(file:///etc/shadow)'}),
    ('description','private\ncommand'),('shell',{'theme':'file:///etc'})])
def test_theme_data_never_grants_paths_code_plugins_or_arbitrary_names(field,value):
    data=spec();data[field]=value
    with pytest.raises((ValueError,PermissionError)):action({'operation':'theme.stage','theme':data})


def test_theme_revision_acknowledgement_cannot_claim_another_mission(tmp_path):
    store=MissionStore(tmp_path/'missions.db');gui=GuiBroker(store)
    row=store.create('fixture','theme','Providerless theme data boundary fixture');store.claim()
    store.session(row['id'],'session','stored');store.dispatching(row['id'])
    epoch=str(uuid.uuid4());gui.attach({'epoch':epoch});key=str(uuid.uuid4())
    gui.submit(row['id'],{'session':'session','id':key,'action':{'operation':'theme.stage','theme':spec()}})
    assert gui.poll(row['id'],{'epoch':epoch})['request']['id']==key
    reply={'name':'haos-t-'+uuid.uuid4().hex,'revision':'a'*64,'scope':'mission-data-theme'}
    with pytest.raises(PermissionError):gui.acknowledge({'epoch':epoch,'id':key,'ok':True,'result':reply})
    reply['name']='haos-t-'+row['id'].replace('-','')
    assert gui.acknowledge({'epoch':epoch,'id':key,'ok':True,'result':reply})['accepted']
    assert gui.result(row['id'],{'session':'session','id':key})['result']==reply
    store.close()
