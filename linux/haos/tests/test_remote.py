import asyncio
import json
import os
import ssl
import subprocess
import time
import uuid

import pytest

from haos.controller import Controller
from haos.remote_control import client,observe,request
from haos.remote_http import Viewer,route,tls_context,RateBudget
from haos.remote_policy import RemotePolicy,certificate_identity
from haos.store import MissionStore


def policy(mid=None,identity='a'*64,**delta):
    value={'version':1,'bind':'127.0.0.1','port':8443,'requests_per_minute':60,'bytes_per_minute':16*1024*1024,
        'devices':[{'id':'fixture-phone','certificate_sha256':identity,'expires_at':time.time()+300,
            'missions':[mid or str(uuid.uuid4())],'content':False,'screenshots':False}]}
    value.update(delta);return value


def test_remote_authority_is_exact_device_expiry_and_mission():
    mid=str(uuid.uuid4());value=policy(mid);p=RemotePolicy(value)
    assert p.authorize('a'*64,mid)['id']=='fixture-phone'
    for identity,mission in [('b'*64,mid),('a'*64,str(uuid.uuid4()))]:
        with pytest.raises(PermissionError):p.authorize(identity,mission)
    with pytest.raises(PermissionError):p.authorize('a'*64,mid,now=value['devices'][0]['expires_at'])
    with pytest.raises(PermissionError):RemotePolicy(dict(value,devices=[])).authorize('a'*64)


@pytest.mark.parametrize('field,value',[('bind','https://evil'),('bind',0),('bind','fe80::1%eth0'),('port',True),('port',22),('requests_per_minute',121),('bytes_per_minute',1),('version',2),('version',True)])
def test_remote_policy_rejects_unbounded_or_ambiguous_configuration(field,value):
    with pytest.raises(ValueError):RemotePolicy(policy(**{field:value}))


@pytest.mark.parametrize('delta',[{'id':'../../root'},{'certificate_sha256':'unverified'},{'missions':['*']},
    {'expires_at':float('inf')},{'content':'yes'},{'screenshots':'yes'},{'capabilities':['owner']}])
def test_device_grants_never_accept_textual_or_unbounded_authority(delta):
    value=policy();value['devices'][0].update(delta)
    with pytest.raises((ValueError,PermissionError)):RemotePolicy(value)


def test_duplicate_device_and_mission_grants_are_denied():
    value=policy();value['devices']*=2
    with pytest.raises(ValueError):RemotePolicy(value)
    value=policy();value['devices'][0]['missions']*=2
    with pytest.raises(ValueError):RemotePolicy(value)


@pytest.mark.parametrize('target',['/api/cancel/'+str(uuid.uuid4()),'/api/mission/../../owner','/api/missions?all=true',
    '/api/events/'+str(uuid.uuid4()),'/api/events/'+str(uuid.uuid4())+'?after=9223372036854775808',
    '/api/mission/'+str(uuid.uuid4())+'?after=0'])
def test_remote_routes_have_no_mutation_or_path_interface(target):
    with pytest.raises((ValueError,PermissionError)):route(target)


def test_remote_budget_charges_actual_bytes_and_requests():
    p=RemotePolicy(policy(requests_per_minute=1,bytes_per_minute=65536));budget=RateBudget()
    budget.reserve('a'*64,p,request=True);budget.reserve('a'*64,p,65536)
    with pytest.raises(OverflowError):budget.reserve('a'*64,p,1)
    with pytest.raises(OverflowError):budget.reserve('a'*64,p,request=True)


def test_actual_mission_projection_is_scoped_content_opt_in_and_audited(tmp_path):
    store=MissionStore(tmp_path/'missions.db');controller=Controller(store,'ws://127.0.0.1:9119/api/ws',set())
    row=store.create('offline-fixture','shared','Sensitive fixture goal');foreign=store.create('offline-fixture','foreign','Private other mission')
    value=policy(row['id']);controller.remote_policy=lambda:RemotePolicy(value)
    call=lambda method,params:observe(controller,{'method':method,'device':'a'*64,'params':params})
    assert call('missions.list',{})==[call('missions.get',{'id':row['id']})]
    assert 'Sensitive fixture goal' not in json.dumps(call('missions.get',{'id':row['id']}))
    assert 'payload' not in call('missions.events',{'id':row['id'],'after':0})[0]
    with pytest.raises(PermissionError):call('missions.get',{'id':foreign['id']})
    for method in ('missions.cancel','missions.answer','gui.attach','gui.ack','policy.write','health'):
        with pytest.raises(PermissionError):call(method,{})
    with pytest.raises(PermissionError):call('applications.snapshot',{'id':row['id']})
    value['devices'][0]['content']=True
    assert call('missions.get',{'id':row['id']})['goal']=='Sensitive fixture goal'
    assert any(e['kind']=='remote.observed' and e['payload']['device']=='fixture-phone' for e in store.events(row['id']))
    value['devices']=[]
    with pytest.raises(PermissionError):call('missions.get',{'id':row['id']})
    assert store.get(row['id'])['state']==row['state'];store.close()


@pytest.fixture
def pki(tmp_path):
    def openssl(*args):
        subprocess.run(['/usr/bin/openssl',*args],cwd=tmp_path,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
    openssl('req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1',
        '-subj','/CN=HAOS Disposable CA','-keyout','ca.key','-out','ca.pem')
    for name,extended in [('server','serverAuth'),('phone','clientAuth'),('unpaired','clientAuth')]:
        openssl('req','-new','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes',
            '-subj','/CN=Disposable '+name,'-keyout',name+'.key','-out',name+'.csr')
        (tmp_path/(name+'.ext')).write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage='+extended+'\nsubjectAltName=IP:127.0.0.1\n')
        openssl('x509','-req','-in',name+'.csr','-CA','ca.pem','-CAkey','ca.key','-CAcreateserial',
            '-days','1','-extfile',name+'.ext','-out',name+'.pem')
        (tmp_path/(name+'.key')).chmod(0o600)
    return tmp_path


def test_real_mtls_unix_mission_observation_reconnect_scope_and_revocation(tmp_path,pki):
    async def exercise():
        store=MissionStore(tmp_path/'missions.db');controller=Controller(store,'ws://127.0.0.1:9119/api/ws',set())
        row=store.create('offline-fixture','tls','Actual persisted mission for real TLS observation')
        foreign=store.create('offline-fixture','other','Private mission must not appear')
        der=ssl.PEM_cert_to_DER_cert((pki/'phone.pem').read_text());fingerprint=certificate_identity(der)
        value=policy(row['id'],fingerprint);value['devices'][0]['content']=True
        controller.remote_policy=lambda:RemotePolicy(value);controller.viewer_uid=os.getuid()
        path=tmp_path/'viewer.sock'
        async def unix_client(reader,writer):await client(controller,reader,writer)
        unix=await asyncio.start_unix_server(unix_client,path=path,limit=8192)
        async def api(data):return await request(data,path=path,controller_uid=os.getuid())
        viewer=Viewer(lambda:RemotePolicy(value),api)
        context=tls_context(str(pki/'server.pem'),str(pki/'server.key'),str(pki/'ca.pem'))
        assert context.minimum_version==ssl.TLSVersion.TLSv1_3 and context.verify_mode==ssl.CERT_REQUIRED
        http=await asyncio.start_server(viewer.client,'127.0.0.1',0,ssl=context,ssl_handshake_timeout=3,limit=8192)
        port=http.sockets[0].getsockname()[1]
        async def fetch(target,certificate='phone',method='GET',extra='',expected=200):
            tls=ssl.create_default_context(cafile=str(pki/'ca.pem'));tls.minimum_version=ssl.TLSVersion.TLSv1_3
            if certificate:tls.load_cert_chain(str(pki/(certificate+'.pem')),str(pki/(certificate+'.key')))
            reader,writer=await asyncio.open_connection('127.0.0.1',port,ssl=tls,server_hostname='127.0.0.1')
            try:
                assert writer.get_extra_info('ssl_object').version()=='TLSv1.3'
                writer.write((method+' '+target+' HTTP/1.1\r\nHost: 127.0.0.1:'+str(port)+'\r\n'+extra+'\r\n').encode());await writer.drain()
                reply=await asyncio.wait_for(reader.read(),5)
                header,body=reply.split(b'\r\n\r\n',1)
                assert int(header.split()[1])==expected
                assert b'Cache-Control: no-store' in header and b'frame-ancestors' in header
                return body
            finally:
                writer.close()
                try:await writer.wait_closed()
                except ssl.SSLError:pass
        try:
            assert row['id'].encode() in await fetch('/api/missions')
            assert foreign['id'].encode() not in await fetch('/api/missions')
            assert json.loads(await fetch('/api/mission/'+row['id']))['goal']==row['goal']
            assert b'Hermes workspace' in await fetch('/')
            await fetch('/api/mission/'+foreign['id'],expected=403)
            await fetch('/api/missions',certificate='unpaired',expected=403)
            with pytest.raises((ssl.SSLError,ConnectionError,ValueError)):
                await fetch('/api/missions',certificate=None)
            await fetch('/api/missions',method='POST',expected=403)
            await fetch('/api/missions',extra='Origin: https://evil.example\r\n',expected=403)
            await fetch('/api/missions',extra='Sec-Fetch-Site: cross-site\r\n',expected=403)
            await fetch('/api/missions',extra='Transfer-Encoding: chunked\r\n',expected=403)
            await fetch('/api/missions',extra='Host: evil.example\r\n',expected=403)
            await fetch('/api/applications/'+row['id'],expected=403)
            value['devices'][0]['screenshots']=True
            snapshot=json.loads(await fetch('/api/applications/'+row['id']))
            assert snapshot['mission']==row['id'] and snapshot['applications']==[]
            assert store.get(row['id'])['state']=='queued'
            value['devices'][0]['expires_at']=time.time()-1
            await fetch('/api/missions',expected=403)
            value['devices'][0]['expires_at']=time.time()+300
            value['requests_per_minute']=1
            await fetch('/api/missions',expected=429)
            value['requests_per_minute']=60;value['devices']=[]
            await fetch('/api/missions',expected=403)
            value['devices']=policy(row['id'],fingerprint)['devices'];controller.viewer_uid=os.getuid()+1
            await fetch('/api/mission/'+row['id'],expected=403)
        finally:
            http.close();await http.wait_closed();unix.close();await unix.wait_closed();store.close()
    asyncio.run(exercise())
