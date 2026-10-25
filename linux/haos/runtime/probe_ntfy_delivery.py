#!/usr/bin/env python3
"""Actual pinned ntfy send codec over loopback HTTP; no external publication."""
import asyncio
import base64
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    from aiohttp import web
    from haos.gateway_ntfy import PreparedNtfyPolicy
    from haos.gateway_ntfy_delivery import Publisher
    from haos.gateway_delivery import delivery_result
    from haos.gateway import GatewayEngine
    from haos.store import MissionStore
    from haos.gateway_ingress import durable_adapter
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes'); os.environ['HERMES_SAFE_MODE']='1'
        from gateway.config import PlatformConfig
        from gateway.platform_registry import PlatformEntry
        from plugins.platforms.ntfy import adapter as module
        class Context:
            def register_platform(self,**kwargs): self.entry=PlatformEntry(**kwargs)
        context=Context(); module.register(context)
        token='disposable-private-publish-token'
        config={'version':1,'connectors':[{'id':'test','platform':'ntfy'}],'bindings':[{
            'id':'owner','connector':'test','sender':'private','chat':'private','scope':'','thread':'',
            'identity':'owner','capabilities':['create'],'since':int(time.time()*1000)-10000,
            'generation':'a'*64,'trust_topic_publishers':True}]}
        policy=lambda:PreparedNtfyPolicy(config)
        binding=dict(config['bindings'][0])
        adapter=durable_adapter(context.entry.adapter_factory(PlatformConfig(enabled=True,extra={
            'topic':'private','publish_topic':'unapproved','server':'https://fixture.invalid','token':token})))
        adapter._haos_native=SimpleNamespace(policy=policy,connector='test')
        publisher=Publisher(adapter)
        state={'status':200,'mode':'normal','requests':[],'index':0,'revoke':False,'rate_after':False,'leaked':0,'expected_auth':'Bearer '+token}
        async def publish(request):
            state['index']+=1
            body=await request.read(); state['requests'].append(body)
            assert request.headers['Authorization']==state['expected_auth']
            assert request.headers['X-Tags']=='hermes-agent' and len(body)<=4096
            assert request.path=='/private'
            code=429 if state['rate_after'] and len(state['requests'])>1 else state['status']
            if code!=200: return web.Response(status=code,text=adapter._token,headers={'Retry-After':'19','Location':'/leak'})
            proof={'event':'message','id':'receipt'+str(state['index']),'topic':'private','time':int(time.time())}
            if state['revoke']: config['bindings']=[]
            if state.get('mutate_grant'): config['bindings'][0]['generation']='b'*64
            mode=state['mode']
            if mode=='credential-id': proof['id']=token
            if mode=='missing': proof.pop('id')
            if mode=='wrong-topic': proof['topic']='unapproved'
            if mode=='malformed': return web.Response(body=b'{',content_type='application/json')
            if mode=='oversize': return web.Response(body=b'A'*65537,content_type='application/json')
            if mode=='lost':
                response=web.StreamResponse(headers={'Content-Type':'application/json','Content-Length':'10000'})
                await response.prepare(request); await response.write(b'{')
                request.transport.close(); return response
            return web.json_response(proof)
        async def leak(request): state['leaked']+=1; return web.Response()
        app=web.Application(); app.router.add_post('/private',publish); app.router.add_route('*','/leak',leak)
        runner=web.AppRunner(app); await runner.setup(); site=web.TCPSite(runner,'127.0.0.1',0); await site.start()
        publisher._target='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
        logs=io.StringIO(); handler=logging.StreamHandler(logs); logger=logging.getLogger('plugins.platforms.ntfy.adapter'); logger.addHandler(handler)
        try:
            result=delivery_result(await publisher.send(binding,'native answer'))
            assert result['status']=='delivered' and result['message_id']=='receipt1' and state['requests']==[b'native answer']
            cases.append('actual_native_codec_publishes_only_exact_owner_topic_and_validated_server_receipt')
            state['requests']=[]; content='🙂'*2100+' exact ending'
            result=delivery_result(await publisher.send(binding,content))
            assert result['status']=='delivered' and len(state['requests'])==3 and b''.join(state['requests'])==content.encode()
            cases.append('native_unicode_chunks_preserve_all_bytes_without_silent_truncation')
            for code in [400,401,403,404,413,429,500,302]:
                state['requests']=[]; state['status']=code
                result=delivery_result(await publisher.send(binding,'single attempt'))
                assert len(state['requests'])==1 and state['leaked']==0
                expected='retry' if code==429 else 'uncertain' if code in {500,302} else 'failed'
                assert result['status']==expected,result
                if code==429: assert result['retry_after']==19
                assert token not in logs.getvalue()
                cases.append('actual_native_http_conservative_single_attempt_'+str(code))
            state['status']=200
            for mode in ['missing','wrong-topic','malformed','oversize','lost','credential-id']:
                state['requests']=[]; state['mode']=mode
                result=delivery_result(await publisher.send(binding,'unclear outcome'))
                assert result=={'status':'uncertain'} and len(state['requests'])==1
                cases.append('native_receipt_'+mode+'_never_fabricates_success_or_resends')
            state['mode']='normal'; state['requests']=[]; state['rate_after']=True
            result=delivery_result(await publisher.send(binding,'🙂'*2100))
            assert result=={'status':'uncertain'} and len(state['requests'])==2
            cases.append('partial_chunk_success_then_429_never_retries_whole_reply')
            state['rate_after']=False; state['requests']=[]; state['revoke']=True
            result=delivery_result(await publisher.send(binding,'🙂'*2100))
            assert result=={'status':'uncertain'} and len(state['requests'])==1
            cases.append('owner_revocation_after_first_chunk_blocks_second_native_post')
            config['bindings']=[dict(binding)]; state['revoke']=False; state['requests']=[]
            state['mutate_grant']=True
            result=delivery_result(await publisher.send(config['bindings'][0],'🙂'*2100))
            assert result=={'status':'uncertain'} and len(state['requests'])==1
            cases.append('mutable_caller_binding_cannot_inherit_regrant_between_chunks')
            config['bindings']=[dict(binding)]; state['mutate_grant']=False; state['requests']=[]
            for name, code, mode, partial, expected in [
                    ('success',200,'normal',False,'delivered'), ('rate',429,'normal',False,'pending'),
                    ('server-error',500,'normal',False,'uncertain'), ('lost',200,'lost',False,'uncertain'),
                    ('partial',200,'normal',True,'uncertain'), ('missing',200,'missing',False,'uncertain')]:
                state['status']=code; state['mode']=mode; state['rate_after']=partial; state['requests']=[]
                path=directory/('outbox-'+name+'.db'); store=MissionStore(path); engine=GatewayEngine(store)
                source={'platform':'ntfy','sender':'private','chat':'private','scope':'','thread':'',
                    'message_id':'outbox-'+name,'is_bot':False,'text':'prepared native outbox fixture'}
                await engine.receive(policy(),'test',source,None)
                obligation=engine.next_delivery(policy())
                result=delivery_result(await publisher.send(binding,'🙂'*2100 if partial else obligation['content']))
                engine.acknowledge(policy(),obligation['id'],{'attempt':obligation['attempt'],**result})
                calls=len(state['requests']); store.close(); store=MissionStore(path); engine=GatewayEngine(store)
                row=store.db.execute('SELECT state FROM gateway_outbox WHERE id=?',(obligation['id'],)).fetchone()
                assert row['state']==expected
                if expected!='pending': assert engine.next_delivery(policy(),now=time.time()+9000) is None
                else: assert engine.next_delivery(policy()) is None
                assert len(state['requests'])==calls
                store.close(); cases.append('actual_reopened_mission_outbox_'+name+'_'+expected)
            state['status']=200; state['mode']='normal'; state['rate_after']=False; state['requests']=[]
            for action in [lambda: adapter.send('unapproved','bypass'),lambda: publisher.post('https://fixture.invalid/private',content=b'bypass',headers={},timeout=15)]:
                try: await action()
                except PermissionError: pass
                else: raise AssertionError('unscoped native publish was allowed')
                assert not state['requests']
            cases.append('direct_native_send_and_unscoped_http_post_have_no_publication_authority')
            result=delivery_result(await publisher.send(binding,'x'*65537))
            assert result=={'status':'failed'} and not state['requests']
            cases.append('oversized_whole_reply_is_refused_before_any_dispatch')
            target=publisher._target
            for basic in ['owner:päss with spaces','owner:password:colon']:
                await publisher.aclose();adapter._token=basic
                publisher=Publisher(adapter);publisher._target=target
                state['expected_auth']='Basic '+base64.b64encode(basic.encode('utf-8')).decode('ascii')
                state['requests']=[]
                result=delivery_result(await publisher.send(binding,'native Basic answer'))
                assert result['status']=='delivered' and state['requests']==[b'native Basic answer']
                cases.append('native_utf8_basic_auth_'+('spaces' if ' ' in basic else 'colon'))
            state['status']=401;state['requests']=[]
            result=delivery_result(await publisher.send(binding,'refused Basic answer'))
            assert result=={'status':'failed'} and len(state['requests'])==1
            assert adapter._token not in logs.getvalue() and state['expected_auth'] not in logs.getvalue()
            cases.append('native_basic_auth_refusal_redacts_raw_and_encoded_credentials')
            state['requests']=[]
            adapter._token='rotated-private-token'
            try: await publisher.send(binding,'old identity')
            except PermissionError: pass
            else: raise AssertionError('rotated identity reused old publisher')
            assert not state['requests']; cases.append('credential_rotation_revokes_old_publisher_before_network')
            assert token not in logs.getvalue()
            cases.append('vendor_secret_error_bodies_never_enter_native_logs')
        finally:
            logger.removeHandler(handler); await publisher.aclose(); await runner.cleanup()
    with tempfile.TemporaryDirectory(prefix='haos-ntfy-delivery-') as value: asyncio.run(exercise(Path(value)))
    receipt={'passed':len(cases),'cases':cases,'actual_pinned_native_send_and_http':True,'loopback_endpoint_replacement_only_in_fixture':True,
             'public_gateway_enabled':True,'external_publish_accepted':False,'installed_service_accepted':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n'); print(json.dumps(receipt))


if __name__=='__main__':main()
