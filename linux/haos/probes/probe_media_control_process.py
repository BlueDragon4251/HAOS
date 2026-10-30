"""Actual distinct-UID media RPC, private ledger and owner-epoch enforcement."""
import base64
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_MEDIA_CONTROL')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit disposable Docker namespace required')
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos','/usr/lib/haos/haos'],check=True)
    root=Path(tempfile.mkdtemp(prefix='haos-media-peer-'));root.chmod(0o755)
    private=root/'control';private.mkdir(mode=0o700);os.chown(private,65532,65532)
    ipc=root/'ipc';ipc.mkdir(mode=0o755);os.chown(ipc,65532,65532)
    policy=root/'policy.json'
    config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
        'id':'owner','connector':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,
        'thread':'','identity':'personal','capabilities':['create','read'],'allow_media':True,'generation':'b'*64,'since':1}]}
    platform=os.environ.get('HAOS_MEDIA_CONTROL_PLATFORM','line')
    if platform not in {'line','email','dingtalk'}:raise ValueError('reviewed private media peer fixture platform required')
    if platform=='email':
        sys.path.insert(0,'/usr/lib/haos')
        from haos.gateway_email import scope
        binding=config['bindings'][0];binding.update(connector='email',sender='owner@example.invalid',chat='owner@example.invalid',
            scope=scope({'address':'haos@example.invalid','imap_host':'imap.example.invalid','imap_port':993}))
        config['connectors']=[{'id':'email','platform':'email'}]
    if platform=='dingtalk':
        sys.path.insert(0,'/usr/lib/haos')
        from haos.gateway_dingtalk import scope
        binding=config['bindings'][0];binding.update(connector='dingtalk',sender='$:LWCP_v1:$opaque-owner',
            chat='cidExactConversation/+=',scope=scope({'client_id':'ding_fixture_app','corp_id':'ding_fixture_corp','robot_code':'ding_fixture_robot'}))
        config['connectors']=[{'id':'dingtalk','platform':'dingtalk'}]
    def publish():
        tmp=root/'policy.next';tmp.write_text(json.dumps(config));os.chown(tmp,0,65532);tmp.chmod(0o640);tmp.replace(policy)
    publish()
    script=root/'worker.py'
    script.write_text('''
import asyncio,json,os,signal,sys
from pathlib import Path
from haos.controller import Controller,MAX_FRAME
from haos.gateway import GatewayPolicy
from haos.store import MissionStore
from haos.sandbox import trusted_json
request=json.load(sys.stdin)
assert os.getgroups()==[]
async def run():
    if request['role']=='control':
        assert set(os.getresuid())=={65532} and set(os.getresgid())=={65532}
        store=MissionStore(Path(request['database']));controller=Controller(store,'unused-private-origin',set())
        controller.gateway_uids={65534}
        from haos.gateway_email import PreparedEmailPolicy
        from haos.gateway_dingtalk import PreparedDingTalkPolicy
        controller.gateway_policy=lambda:(PreparedDingTalkPolicy if request['platform']=='dingtalk' else PreparedEmailPolicy if request['platform']=='email' else GatewayPolicy)(trusted_json(Path(request['policy'])))
        async def incoming(reader,writer):await controller.client(reader,writer,gateway=True)
        stop=asyncio.Event();asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,stop.set)
        server=await asyncio.start_unix_server(incoming,path=request['socket'],limit=MAX_FRAME)
        # Deliberately permit filesystem connection: the negative test must
        # reach SO_PEERCRED, rather than rely only on socket directory modes.
        os.chmod(request['socket'],0o666)
        print(json.dumps({'ready':True,'uid':os.geteuid()}),flush=True)
        try:await stop.wait()
        finally:server.close();await server.wait_closed();store.close()
        return
    assert set(os.getresuid())=={request['uid']} and set(os.getresgid())=={request['uid']}
    try:Path(request['database']).read_bytes()
    except PermissionError:pass
    else:raise AssertionError('non-controller UID read private media ledger')
    if request['role']=='client-runtime':
        from haos import gateway_runtime
        gateway_runtime.SOCKET=request['socket']
        result=await gateway_runtime.call(request['method'],request['params'])
        print(json.dumps({'ok':True,'result':result}),flush=True);return
    reader,writer=await asyncio.open_unix_connection(request['socket'])
    frame={'method':request['method'],'params':request['params'],'uid':0,'role':'owner'}
    # An unauthorized peer is refused before a request is read. Do not race
    # that intentional early close with a pointless client write/drain.
    if request['uid']!=65533:
        writer.write(json.dumps(frame).encode()+b'\\n');await writer.drain()
    result=json.loads(await reader.readline());writer.close();await writer.wait_closed()
    print(json.dumps(result),flush=True)
asyncio.run(run())
''');script.chmod(0o644)
    env={'PATH':'/usr/bin:/bin','PYTHONPATH':'/usr/lib/haos','PYTHONDONTWRITEBYTECODE':'1','LANG':'C.UTF-8'}
    database=private/'missions.db';socket=ipc/'gateway.sock'
    server=subprocess.Popen([sys.executable,str(script)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,user=65532,group=65532,extra_groups=[],umask=0o077,env=env)
    common={'socket':str(socket),'database':str(database)}
    try:
        stdout,stderr=None,None
        server.stdin.write(json.dumps({**common,'role':'control','policy':str(policy),'platform':platform}));server.stdin.close()
        # A bounded pipe read also reports an early child failure without ever
        # printing the private byte payload from a producer request.
        import select
        assert select.select([server.stdout],[],[],15)[0],'private controller did not start'
        ready=server.stdout.readline()
        if not ready:raise AssertionError('private media controller failed: '+server.stderr.read()[-2000:])
        assert json.loads(ready)=={'ready':True,'uid':65532}
        def request(uid,method,params,*,runtime=False):
            value={**common,'role':'client-runtime' if runtime else 'client','uid':uid,'method':method,'params':params}
            child=subprocess.run([sys.executable,str(script)],input=json.dumps(value),capture_output=True,text=True,timeout=15,
                user=uid,group=uid,extra_groups=[],umask=0o077,env=env)
            assert child.returncode==0,child.stderr[-2000:]
            return json.loads(child.stdout)
        sys.path.insert(0,'/usr/lib/haos')
        from haos.gateway_media import describe
        data=b'disposable private media payload'
        binding=config['bindings'][0]
        event={'platform':platform,'sender':binding['sender'],'chat':binding['chat'],'scope':binding['scope'],'thread':'',
            'message_id':'c'*64,'is_bot':False,'text':'Inspect the attached document.'}
        params={'connector':platform,'envelope':event,'descriptor':describe(data,'document')}
        started=request(65534,'gateway.media.begin',params);assert started['ok']
        identity=started['result']['id'];payload={'id':identity,'offset':0,'data':base64.b64encode(data).decode()}
        assert request(65534,'gateway.media.chunk',payload)['result']['ready']
        cases=['actual_gateway_uid_uploads_over_kernel_peer_authenticated_socket_without_reading_controller_ledger']
        from haos.gateway import digest
        unicode_event={**event,'message_id':'d'*64,'text':'😀'*32000}
        unicode_params={**params,'envelope':unicode_event}
        large=request(65534,'gateway.media.begin',unicode_params,runtime=True);assert large['ok']
        with sqlite3.connect(database) as observer:
            assert observer.execute('SELECT envelope_digest FROM gateway_media_uploads WHERE id=?',(large['result']['id'],)).fetchone()[0]==digest(unicode_event)
        cases.append('actual_gateway_runtime_client_transfers_32000_multibyte_characters_over_real_kernel_socket_without_truncation_or_frame_limit_increase')
        refused=request(65533,'gateway.media.begin',params)
        assert refused['ok'] is False and 'peer is not authorized' in refused['error']
        cases.append('actual_agent_uid_reaches_permissive_socket_but_is_denied_before_any_frame_and_cannot_read_private_ledger')
        for method in ['gateway.output.begin','gateway.output.chunk']:
            refused=request(65533,method,{'delivery':'f'*64,'attempt':1,'path':'/owner/private.png'})
            assert refused['ok'] is False and 'peer is not authorized' in refused['error']
        refused=request(65534,'gateway.output.begin',{'delivery':'f'*64,'attempt':1,'path':'/owner/private.png'})
        assert refused['ok'] is False and 'not currently in flight' in refused['error']
        cases.append('actual_agent_peer_cannot_request_output_exports_and_gateway_cannot_invent_a_host_path_export')

        assert request(65534,'missions.list',{})['ok'] is False
        cases.append('actual_gateway_uid_cannot_gain_owner_methods_through_forged_uid_zero_and_owner_json_fields')
        config['bindings'][0]['allow_media']=False;publish()
        assert request(65534,'gateway.media.chunk',payload)['ok'] is False
        cases.append('actual_owner_policy_withdrawal_blocks_a_later_chunk_on_the_same_connection_interface')
        config['bindings'][0].update(allow_media=True,generation='e'*64);publish()
        old=request(65534,'gateway.receive',{'connector':platform,'envelope':event,'media':[identity]})
        assert old['ok'] is False
        with sqlite3.connect(database) as observer:assert observer.execute('SELECT COUNT(*) FROM missions').fetchone()[0]==0
        fresh=request(65534,'gateway.media.begin',params);assert fresh['ok'] and fresh['result']['id']!=identity
        payload['id']=fresh['result']['id'];assert request(65534,'gateway.media.chunk',payload)['result']['ready']
        admitted=request(65534,'gateway.receive',{'connector':platform,'envelope':event,'media':[payload['id']]})
        assert admitted['ok']
        with sqlite3.connect(database) as observer:
            assert observer.execute('SELECT COUNT(*) FROM missions').fetchone()[0]==1
            assert observer.execute("SELECT COUNT(*) FROM gateway_media_uploads WHERE state='attached'").fetchone()[0]==1
        cases.append('actual_new_owner_epoch_cannot_rebind_old_upload_and_requires_new_durable_media_admission')
        assert database.stat().st_uid==65532 and database.stat().st_mode&0o077==0
        print(json.dumps({'passed':len(cases),'cases':cases,'actual_uids':[0,65532,65533,65534],
            'actual_kernel_so_peercred':True,'socket_filesystem_permission_is_not_the_negative_gate':True,
            'gateway_platform':platform,'prepared_email_policy_is_fixture':platform=='email','prepared_dingtalk_policy_is_fixture':platform=='dingtalk',
            'optional_hermes_sdk_imported':False,'external_or_installed_acceptance':False},indent=2))
    finally:
        if server.poll() is None:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)


if __name__=='__main__':main()
