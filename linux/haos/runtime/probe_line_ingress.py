#!/usr/bin/env python3
"""Real pinned LINE HMAC verifier/codec and private durable admission; no listener."""
import asyncio
import base64
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import GatewayPolicy
    from haos.gateway_line_ingress import snapshot,capture,dispatch_stored,install
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_raw import NativeInbox
    from haos.gateway_runtime import adapter_envelope
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes');os.environ['HERMES_SAFE_MODE']='1'
        from gateway.config import PlatformConfig
        from plugins.platforms.line.adapter import LineAdapter
        destination='U'+'d'*32;user='U'+'a'*32;group='C'+'b'*32
        config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
            'id':'owner','connector':'line','sender':user,'chat':group,'scope':destination,'thread':'',
            'identity':'owner','capabilities':['create','read'],'generation':'a'*64,'since':int((time.time()-10)*1000)}]}
        policy=lambda:GatewayPolicy(config)
        assert policy().connectors['line']['platform']=='line'
        cases.append('public_line_requires_exact_independent_owner_route')
        inbox=NativeInbox(directory/'native.db',Redactor())
        adapter=install(durable_adapter(LineAdapter(PlatformConfig(enabled=True,extra={'channel_secret':'disposable-line-secret','channel_access_token':'disposable-private-access'}))))
        adapter._haos_native=SimpleNamespace(connector='line',policy=policy,inbox=inbox)
        accepted=[];failure=[False]
        def receive(event):
            source=adapter_envelope(event,'line')
            with sqlite3.connect(directory/'native.db') as observer:
                assert observer.execute('SELECT state FROM native_inbox WHERE message_id=?',(source['message_id'],)).fetchone()==('processing',)
            if failure[0]:raise ConnectionError('disposable local interruption')
            accepted.append(source);return True
        adapter.set_durable_message_handler(receive)
        event={'type':'message','mode':'active','timestamp':int(time.time()*1000),
            'webhookEventId':'01K8'+'A'*22,
            'source':{'type':'group','userId':user,'groupId':group},'replyToken':'private-single-use-fixture',
            'message':{'type':'text','id':'1234','text':'hello owner'}}
        def signed(events=None,**changes):
            payload={'destination':destination,'events':events if events is not None else [event]};payload.update(changes)
            body=json.dumps(payload).encode();return body,base64.b64encode(hmac.new(adapter.channel_secret.encode(),body,hashlib.sha256).digest()).decode()
        authority=snapshot(policy(),'line',destination)
        body,sig=signed();key=capture(adapter,body,sig,authority)[0]
        assert await dispatch_stored(adapter,key) and accepted[0]['sender']==user and accepted[0]['chat']==group
        assert accepted[0]['scope']==destination and accepted[0]['text']=='hello owner'
        assert not adapter._reply_tokens and not await dispatch_stored(adapter,key)
        assert 'private-single-use-fixture' not in inbox.db.execute('SELECT payload FROM native_inbox').fetchone()[0]
        cases.append('actual_native_hmac_and_text_codec_after_observable_commit_strip_single_use_reply_capability')
        cases.append('same_signed_event_cannot_repeat_local_admission')
        reflected={**event,'webhookEventId':'01K8'+'D'*22,'message':{**event['message'],
            'text':' '.join([adapter.channel_secret,adapter.channel_access_token,event['replyToken']])}}
        rb,rs=signed([reflected]);reflected_key=capture(adapter,rb,rs,authority)[0]
        payload=inbox.db.execute('SELECT payload FROM native_inbox WHERE id=?',(reflected_key,)).fetchone()[0]
        assert all(secret not in payload for secret in [adapter.channel_secret,adapter.channel_access_token,event['replyToken']])
        assert await dispatch_stored(adapter,reflected_key)
        assert accepted[-1]['text']=='[REDACTED] [REDACTED] [REDACTED]'
        cases.append('reflected_channel_secret_access_and_single_use_reply_tokens_redacted_before_persistence_and_native_decode')
        for label,alter in [
            ('unknown_user',{'source':{**event['source'],'userId':'U'+'f'*32}}),
            ('unknown_group',{'source':{**event['source'],'groupId':'C'+'f'*32}}),
            ('missing_user',{'source':{'type':'group','groupId':group}}),
            ('standby',{'mode':'standby'}),('media',{'message':{'type':'image','id':'1234'}}),
            ('missing_original_time',{'timestamp':None}),('boolean_time',{'timestamp':True}),
            ('invalid_event_id',{'webhookEventId':'attacker'}),('empty_text',{'message':{**event['message'],'text':' '}}),
            ('ambiguous_source',{'source':{**event['source'],'roomId':'R'+'f'*32}})]:
            bad={**event,**alter};b,s=signed([bad]);assert capture(adapter,b,s,authority)==[],label;cases.append(label)
        for label,b,s in [('tampered_body',body+b' ',sig),('invalid_signature',body,'A'*43+'='),('oversized_body',b'x'*65537,sig)]:
            try:capture(adapter,b,s,authority)
            except PermissionError:pass
            else:raise AssertionError(label)
            cases.append(label)
        for label,events,changes in [('wrong_destination',[event],{'destination':'U'+'f'*32}),
                ('stale_event',[{**event,'timestamp':config['bindings'][0]['since']-1}],{}),
                ('future_event',[{**event,'timestamp':int((time.time()+301)*1000)}],{}),
                ('oversized_batch',[event]*65,{})]:
            b,s=signed(events,**changes)
            try:capture(adapter,b,s,authority)
            except PermissionError:pass
            else:raise AssertionError(label)
            cases.append(label)
        duplicate=b'{"destination":"'+destination.encode()+b'","destination":"'+destination.encode()+b'","events":[]}'
        ds=base64.b64encode(hmac.new(adapter.channel_secret.encode(),duplicate,hashlib.sha256).digest()).decode()
        try:capture(adapter,duplicate,ds,authority)
        except ValueError:pass
        else:raise AssertionError('duplicate signed JSON admitted')
        cases.append('duplicate_signed_json_rejected')
        for name in ['connect','_handle_webhook','_dispatch_event','_handle_message_event','_handle_postback_event',
                '_download_media','_handle_media','send','send_typing','send_image_file','send_voice','send_video']:
            try:await getattr(adapter,name)()
            except PermissionError:pass
            else:raise AssertionError(name)
            cases.append('raw_native_'+name+'_denied')
        next_event={**event,'webhookEventId':'01K8'+'B'*22};b,s=signed([next_event]);key=capture(adapter,b,s,authority)[0]
        failure[0]=True
        try:await dispatch_stored(adapter,key)
        except ConnectionError:pass
        else:raise AssertionError('interrupted local admission acknowledged')
        inbox.close();inbox=NativeInbox(directory/'native.db',Redactor());adapter._haos_native.inbox=inbox;failure[0]=False
        assert not await dispatch_stored(adapter,key), 'persisted local retry deadline was ignored'
        # Advance only the disposable fixture deadline; production backoff stays intact.
        inbox.db.execute('UPDATE native_inbox SET next_attempt=0 WHERE id=?',(key,))
        assert await dispatch_stored(adapter,key) and len(accepted)==3
        cases.append('actual_sqlite_reopen_retries_failed_local_admission_without_external_side_effect')
        next_event={**event,'webhookEventId':'01K8'+'C'*22};b,s=signed([next_event]);key=capture(adapter,b,s,authority)[0]
        config['bindings']=[]
        assert not await dispatch_stored(adapter,key)
        cases.append('owner_withdrawal_blocks_retained_native_event')
        inbox.close()
    with tempfile.TemporaryDirectory(prefix='haos-line-native-') as temporary:asyncio.run(exercise(Path(temporary)))
    receipt={'passed':len(cases),'cases':cases,'actual_pinned_hmac_and_native_codec_and_sqlite':True,
        'public_gateway_enabled':True,'listener_or_external_message_or_account_acceptance':False}
    text=json.dumps(receipt,indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(text)
    print(text,end='')


if __name__=='__main__':main()
