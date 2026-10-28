#!/usr/bin/env python3
"""Actual authenticated backend artifacts into bounded prepared email output."""
import asyncio
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace


async def session(base,token,workspace):
    from PIL import Image
    from websockets.asyncio.client import connect
    from gateway.config import PlatformConfig
    from plugins.platforms.email.adapter import EmailAdapter
    from hermes_state import SessionDB
    from haos.hermes import HermesConnection,websocket_url
    from haos.controller import Controller
    from haos.store import MissionStore
    from haos.gateway_email import PreparedEmailPolicy,scope as mailbox_scope
    from haos.gateway_email_output import Output
    from haos.gateway_matrix_profile import scope
    from haos.gateway_raw import NativeInbox
    from haos.gateway import digest
    from haos.redaction import Redactor
    root=workspace/'email-private';root.mkdir(mode=0o700)
    value={'address':'haos@example.invalid','password':'private-email-fixture','imap_host':'imap.example.invalid','imap_port':993,
        'imap_security':'tls','smtp_host':'smtp.example.invalid','smtp_port':465,'smtp_security':'tls','authserv_id':'mx.example.invalid'}
    sender='owner@example.invalid';binding={'id':'owner','connector':'email','sender':sender,'chat':sender,'scope':mailbox_scope(value),
        'thread':'','identity':'personal','capabilities':['create','read'],'allow_outbound_media':True,'generation':'b'*64,'since':1}
    config={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[binding]};policy=lambda:PreparedEmailPolicy(config)
    image=BytesIO();Image.new('RGB',(3,2),(10,20,30)).save(image,format='PNG')
    files={'image.png':image.getvalue(),'document.txt':b'A bounded actual exported email document.'}
    for name,data in files.items():(workspace/name).write_bytes(data)
    result_text='Email result fixture\n'+'\n'.join('MEDIA:'+str(workspace/name) for name in files)
    async def ignore(*_args):pass
    async with connect(websocket_url(base,token),proxy=None) as channel:
        rpc=HermesConnection(channel,ignore,ignore)
        try:native=await rpc.request('session.create',{'source':'herald_os','cwd':str(workspace),'close_on_disconnect':True})
        finally:await rpc.close()
    db=SessionDB(workspace.parent/'.hermes/state.db')
    try:db.create_session(native['stored_session_id'],source='herald_os',cwd=str(workspace))
    finally:db.close()
    store=MissionStore(root/'controller.db');controller=Controller(store,websocket_url(base,token),set());controller.gateway_policy=policy
    event={'platform':'email','sender':sender,'chat':sender,'scope':mailbox_scope(value),'thread':'',
        'message_id':'c'*64,'is_bot':False,'text':'Create result files.'}
    admitted=await controller.gateway.receive(policy(),'email',event,None);mid=admitted['mission_id']
    store.claim();store.session(mid,native['session_id'],native['stored_session_id']);store.settle(mid,'completed',result=result_text)
    deliveries=[]
    while (delivery:=controller.gateway.next_delivery(policy())) is not None:deliveries.append(delivery)
    delivery=next(item for item in deliveries if 'MEDIA:' in item['content'])
    inbox=NativeInbox(root/'native.db',Redactor([value['password']]))
    home=root/'home';home.mkdir(mode=0o700)
    env={'EMAIL_'+key.upper():str(item) for key,item in value.items() if key!='authserv_id'}
    env.update(EMAIL_AUTHSERV_ID=value['authserv_id'],EMAIL_TRUST_FROM_HEADER='false')
    with scope(home,env):adapter=EmailAdapter(PlatformConfig(enabled=True,extra={'skip_attachments':True,'require_authenticated_sender':True,
        'authserv_id':value['authserv_id']}))
    adapter._haos_native=SimpleNamespace(connector='email',policy=policy,inbox=inbox)
    route={'binding_id':binding['id'],'binding_digest':digest(binding)}
    def current():policy().current_binding(route)
    adapter._haos_email_check=current;adapter._mark_connected();output=Output(adapter);calls=[];cases=[]
    async def call(method,params):
        calls.append((method,dict(params)));return await controller.gateway_dispatch({'method':method,'params':params})
    try:
        prepared=await output.prepare(delivery,call)
        assert [item['data'] for item in prepared['items']]==list(files.values())
        assert [item['name'] for item in prepared['items']]==['result-0.png','result-1.txt']
        assert 'MEDIA:' not in prepared['text'] and str(workspace) not in prepared['text']
        assert all('path' not in item for item in prepared['items'])
        cases.append('actual_authenticated_backend_exports_only_exact_marked_completed_source_session_files_as_private_bytes')
        (workspace/'document.txt').write_bytes(b'Changed source must not replace a durable snapshot.')
        repeated=await output.prepare(delivery,call);assert repeated==prepared
        cases.append('durable_controller_snapshot_does_not_reread_a_changed_agent_file_on_repeated_preparation')
        before=len(calls)
        try:await controller.gateway_dispatch({'method':'gateway.output.begin','params':{
            'delivery':delivery['id'],'attempt':delivery['attempt'],'path':'/owner/private.png'}})
        except PermissionError:pass
        else:raise AssertionError('unmarked owner path was exported')
        cases.append('arbitrary_or_unmarked_host_path_cannot_become_an_email_output_export')
        binding['allow_outbound_media']=False
        try:await output.prepare(delivery,call)
        except PermissionError:pass
        else:raise AssertionError('withdrawn binding prepared old email output')
        assert len(calls)==before
        cases.append('owner_withdrawal_refuses_the_old_delivery_before_any_further_private_read')
        route['binding_digest']=digest(binding)
        stripped=await output.prepare({**delivery,**route},call)
        assert not stripped['items'] and 'separate owner approval' in stripped['text'] and len(calls)==before
        cases.append('fresh_route_without_output_consent_strips_paths_and_performs_no_private_file_reads')
    finally:inbox.close();store.close()
    return {'passed':len(cases),'cases':cases,'actual_authenticated_backend_artifact_reader':True,
        'completed_session_and_connected_mail_transport_are_fixtures':True,'prepared_only_not_public':True,
        'smtp_write_worker_isolation_external_mail_or_inference_acceptance':False}


if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from probe_backend import probe
    report=probe(Path(sys.argv[2]).resolve(strict=True),session_probe=session)
    Path(sys.argv[3]).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
