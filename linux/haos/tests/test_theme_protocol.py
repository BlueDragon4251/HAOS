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
    assert gui.lease(row['id'],{'epoch':epoch,'id':key})=={'authorized':True}
    reply={'name':'haos-t-'+uuid.uuid4().hex,'revision':'a'*64,'scope':'mission-data-theme'}
    with pytest.raises(PermissionError):gui.acknowledge({'epoch':epoch,'id':key,'ok':True,'result':reply})
    reply['name']='haos-t-'+row['id'].replace('-','')
    assert gui.acknowledge({'epoch':epoch,'id':key,'ok':True,'result':reply})['accepted']
    assert gui.result(row['id'],{'session':'session','id':key})['result']==reply
    assert gui.lease(row['id'],{'epoch':epoch,'id':key})=={'authorized':False}
    store.close()


def test_native_lease_revocation_does_not_dispatch_other_queued_work(tmp_path):
    store=MissionStore(tmp_path/'missions.db');gui=GuiBroker(store)
    row=store.create('fixture','lease','Providerless native lease fixture');store.claim()
    store.session(row['id'],'session','stored');store.dispatching(row['id'])
    epoch=str(uuid.uuid4());gui.attach({'epoch':epoch});ids=[str(uuid.uuid4()),str(uuid.uuid4())]
    for key in ids:gui.submit(row['id'],{'session':'session','id':key,'action':{'operation':'theme.sdk'}})
    assert gui.poll(row['id'],{'epoch':epoch})['request']['id']==ids[0]
    assert gui.lease(row['id'],{'epoch':epoch,'id':ids[0]})['authorized']
    assert gui.result(row['id'],{'session':'session','id':ids[1]})['state']=='pending'
    store.request_cancel(row['id'],'fixture')
    assert not gui.lease(row['id'],{'epoch':epoch,'id':ids[0]})['authorized']
    with pytest.raises(PermissionError):gui.lease(row['id'],{'epoch':str(uuid.uuid4()),'id':ids[0]})
    store.close()


@pytest.mark.parametrize('op',['theme.preview','theme.apply'])
def test_only_exact_saved_revision_ids_can_be_observed_or_activated(op):
    assert action({'operation':op,'revision':'a'*64})['revision']=='a'*64
    for value in ('latest','../owner','a'*63):
        with pytest.raises(PermissionError):action({'operation':op,'revision':value})
    with pytest.raises(PermissionError):action({'operation':op,'revision':'a'*64,'name':'owner'})


def test_real_preview_bytes_are_ephemeral_and_false_render_checks_cannot_claim_pass(tmp_path):
    import base64,hashlib
    from haos.gui import action_age_limit
    store=MissionStore(tmp_path/'missions.db');gui=GuiBroker(store)
    row=store.create('fixture','preview','Providerless preview receipt boundary');store.claim()
    store.session(row['id'],'session','stored');store.dispatching(row['id'])
    epoch=str(uuid.uuid4());gui.attach({'epoch':epoch});key=str(uuid.uuid4())
    gui.submit(row['id'],{'session':'session','id':key,'action':{'operation':'theme.preview','revision':'a'*64}})
    gui.poll(row['id'],{'epoch':epoch})
    # Unit-only transport payload; actual pixel/render proof has a separate
    # mandatory Chromium/Wayland gate. No model execution is represented here.
    pixels=b'\xff\xd8'+b'x'*200+b'\xff\xd9';encoded=base64.b64encode(pixels).decode()
    checks={k:True for k in ('sandbox','rendered','controlsVisible','textContrast','secondaryContrast','controlContrast','rasterDecoded')}
    value={'name':'haos-t-'+row['id'].replace('-',''),'revision':'a'*64,'passed':True,'checks':checks,
        'stylesheet_sha256':'b'*64,'png_sha256':'c'*64,'mime':'image/jpeg','bytes':len(pixels),
        'sha256':hashlib.sha256(pixels).hexdigest(),'base64':encoded}
    bad=dict(value,checks=dict(checks,rendered=False))
    with pytest.raises(ValueError):receipt('theme.preview',bad)
    assert gui.acknowledge({'epoch':epoch,'id':key,'ok':True,'result':value})['accepted']
    assert gui.result(row['id'],{'session':'session','id':key})['result']['base64']==encoded
    assert encoded not in store.db.execute('SELECT result FROM gui_actions WHERE id=?',(key,)).fetchone()[0]
    assert encoded not in str(store.events(row['id']))
    assert action_age_limit('theme.apply')==45
    for op in ('open','type','capture','theme.preview','app.start'):assert action_age_limit(op)==20
    store.close()
