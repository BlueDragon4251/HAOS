"""Real distinct gateway/controller UID offline Feishu decisions; no SDK or network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists()
            or os.environ.get('HAOS_DISPOSABLE_FEISHU_RECOVERY')!='1' or Path('/usr/lib/haos').exists()
            or Path('/etc/haos').exists() or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit offline Feishu recovery namespace required')
    installed=Path('/usr/lib/haos');installed.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(installed/'haos')],check=True)
    with Path('/etc/passwd').open('a') as stream:
        stream.write('haos-gateway:x:65534:65534:Disposable gateway:/nonexistent:/usr/sbin/nologin\n')
        stream.write('haos-control:x:65532:65532:Disposable controller:/nonexistent:/usr/sbin/nologin\n')
    for name,uid in [('haos-gateway',65534),('haos-control',65532)]:
        directory=Path('/var/lib')/name;directory.mkdir(mode=0o700);os.chown(directory,uid,uid)
    root=Path(tempfile.mkdtemp(prefix='haos-feishu-recovery-'));root.chmod(0o755)
    canary=root/'owner-secret';canary.write_text('preserve-owner-fixture');canary.chmod(0o600)
    sys.path.insert(0,str(installed))
    from haos.gateway_feishu import scope
    value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-recovery-fixture','domain':'feishu',
        'tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
    config={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[{
        'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,'scope':scope(value),'thread':'',
        'identity':'personal','capabilities':['create','read'],'generation':'d'*64,'since':1}]}
    seed=root/'seed.py';seed.write_text('''
import asyncio,json,os,sys,time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,'/usr/lib/haos')
from haos.gateway import GatewayEngine
from haos.gateway_feishu import PreparedFeishuPolicy
request=json.load(sys.stdin);policy=PreparedFeishuPolicy(request['policy']);binding=policy.bindings['owner']
assert os.getgroups()==[]
try:Path(request['canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('service read owner secret')
if os.geteuid()==65532:
    from haos.store import MissionStore
    store=MissionStore(Path('/var/lib/haos-control/missions.db'));engine=GatewayEngine(store)
    envelope={'platform':'feishu','sender':binding['sender'],'chat':binding['chat'],'scope':binding['scope'],'thread':'',
        'message_id':'om_'+'f'*32,'is_bot':False,'text':'Controlled offline recovery fixture goal.'}
    asyncio.run(engine.receive(policy,'feishu',envelope,None));delivery=engine.next_delivery(policy)
    asyncio.run(engine.receive(policy,'feishu',{**envelope,'message_id':'om_'+'e'*32},None));second=engine.next_delivery(policy)
    print(json.dumps({'delivery_id':delivery['id'],'attempt':delivery['attempt'],'second_delivery_id':second['id']}));store.close()
else:
    assert os.geteuid()==65534
    from haos.gateway_raw import NativeInbox
    from haos.gateway_feishu_delivery import Publisher
    from haos.redaction import Redactor
    inbox=NativeInbox(Path('/var/lib/haos-gateway/native-inbox.db'),Redactor())
    publisher=Publisher(SimpleNamespace(_haos_native=SimpleNamespace(connector='feishu',inbox=inbox),_haos_feishu_value=request['credentials']))
    now=time.time()
    for identity,state,receipt in [(request['delivery_id'],'uncertain',''),(request['second_delivery_id'],'confirmed','om_'+'d'*32)]:
        inbox.db.execute('INSERT INTO feishu_delivery_intents VALUES(?,?,?,?,?,?,?,?,?,?)',
            (identity,1,'feishu',publisher.credential_scope,'a'*64,state,receipt,'',now,now))
    inbox.db.execute("UPDATE feishu_delivery_backoff SET status='rate-limited',next_attempt=?,updated_at=?",(now+600,now))
    from haos.gateway import digest
    import hashlib
    profiles=Path('/var/lib/haos-gateway/profiles');profiles.mkdir(mode=0o700)
    profile=profiles/('feishu-'+'a'*64);profile.mkdir(mode=0o700)
    payload=b'declared offline source fixture';checksum=hashlib.sha256(payload).hexdigest()
    approval={'binding_id':binding['id'],'binding_digest':digest(binding),'credential_scope':publisher.credential_scope,
        'envelope':{'platform':'feishu'}}
    original=NativeInbox(profile/'originals.db',Redactor())
    original.db.execute('CREATE TABLE feishu_raw_events(id TEXT PRIMARY KEY,source_key TEXT NOT NULL UNIQUE,connector TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,sha256 TEXT NOT NULL,semantic_sha256 TEXT NOT NULL,metadata TEXT NOT NULL,data BLOB NOT NULL,created_at REAL NOT NULL)')
    meta=json.dumps({'approval':approval,'resources':[],'envelope_sha256':'b'*64})
    original.db.execute('INSERT INTO feishu_raw_events VALUES(?,?,?,?,?,?,?,?,?,?,?)',
        ('c'*64,'d'*64,'feishu',binding['id'],digest(binding),publisher.credential_scope,checksum,'b'*64,meta,payload,now))
    original.close()
    webhook=NativeInbox(profile/'webhooks.db',Redactor())
    webhook.db.execute('CREATE TABLE feishu_webhook_receipts(id TEXT PRIMARY KEY,credential_scope TEXT NOT NULL,headers TEXT NOT NULL,wire BLOB NOT NULL,wire_sha256 TEXT NOT NULL,proof TEXT NOT NULL,state TEXT NOT NULL,source_key TEXT,created_at REAL NOT NULL)')
    webhook.db.execute('INSERT INTO feishu_webhook_receipts VALUES(?,?,?,?,?,?,?,?,?)',
        ('c'*64,publisher.credential_scope,'{}',payload,checksum,json.dumps(approval),'captured','d'*64,now))
    webhook.close()
    print(json.dumps({'seeded':True}));inbox.close()
''');seed.chmod(0o644)
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'};cases=[]
    def execute(uid,args,data,accepted=True):
        result=subprocess.run([sys.executable,'-E','-s',*args],input=json.dumps(data),text=True,capture_output=True,
            user=uid,group=uid,extra_groups=[],umask=0o077,cwd=installed,env=env,timeout=15)
        if not accepted:assert result.returncode!=0 and len(result.stderr)<8192;return
        assert result.returncode==0,result.stderr[-2000:]
        assert len(result.stdout)<256*1024 and value['app_secret'] not in result.stdout+result.stderr
        return json.loads(result.stdout)
    control=execute(65532,[str(seed)],{'policy':config,'canary':str(canary)})
    execute(65534,[str(seed)],{'policy':config,'canary':str(canary),'credentials':value,**control})
    def raw(uid,action,params,accepted=True):return execute(uid,['-m','haos.gateway_raw_recovery'],{'action':action,'policy':config,'params':params},accepted)
    def ledger(uid,action,params,accepted=True):return execute(uid,['-m','haos.gateway_recovery'],{'action':action,'policy':config,'params':params},accepted)
    for uid in [0,65532,65533]:raw(uid,'ingress',{'after':0},False)
    for uid in [0,65533,65534]:ledger(uid,'deliveries',{'after':0},False)
    cases.append('actual_root_agent_and_wrong_service_uids_cannot_open_private_offline_helpers_even_with_supplied_owner_fields')
    inventory=raw(65534,'ingress',{'after':0});assert len(inventory['native_outgoing'])==2
    intent=next(item for item in inventory['native_outgoing'] if item['delivery_id']==control['delivery_id'])
    account=inventory['feishu_accounts'][0];assert account['status']=='rate-limited' and account['network_requested'] is False
    cases.append('actual_gateway_uid_inspects_only_finite_opaque_delivery_and_account_metadata_without_optional_runtime')
    permission={'connector':'feishu','delivery_id':control['delivery_id'],'attempt':1,'snapshot_sha256':intent['snapshot_sha256'],
        'owner_uid':1000,'note_sha256':'b'*64,'confirmed':True,'confirmed_not_delivered':True}
    raw(65534,'approve-feishu-retry',{**permission,'snapshot_sha256':'c'*64},False)
    raw(65534,'approve-feishu-retry',{**permission,'confirmed_not_delivered':False},False)
    known=next(item for item in inventory['native_outgoing'] if item['state']=='confirmed')
    raw(65534,'approve-feishu-retry',{**permission,'delivery_id':known['delivery_id'],'snapshot_sha256':known['snapshot_sha256']},False)
    cases.append('actual_private_helper_refuses_stale_inspection_missing_non_delivery_confirmation_and_confirmed_acceptance')
    first=raw(65534,'approve-feishu-retry',permission)
    assert first['controller_reconciliation_still_required'] and first['network_requested'] is False
    assert raw(65534,'approve-feishu-retry',permission)==first
    assert ledger(65532,'deliveries',{'after':0})['deliveries'][0]['state']=='sending'
    current=raw(65534,'ingress',{'after':0});assert current['feishu_accounts']==inventory['feishu_accounts']
    cases.append('gateway_owner_decision_is_idempotent_and_preserves_account_deadline_and_separate_controller_obligation')
    decision={'delivery_id':control['delivery_id'],'attempt':1,'decision':'retry','owner_uid':1000,'note_sha256':'b'*64,
        'receipt':None,'confirmed_not_delivered':True}
    assert ledger(65532,'reconcile-delivery',decision)['state']=='pending'
    assert next(item for item in raw(65534,'ingress',{'after':0})['native_outgoing'] if item['delivery_id']==control['delivery_id'])['state']=='owner-retry-approved'
    cases.append('distinct_actual_service_uids_record_two_offline_owner_decisions_without_network_or_rewriting_prior_gateway_intent')
    accepted={'delivery_id':control['second_delivery_id'],'attempt':1,'decision':'delivered','owner_uid':1000,
        'note_sha256':'b'*64,'receipt':'smtp_accept_'+'a'*64,'confirmed_not_delivered':False}
    ledger(65532,'reconcile-delivery',accepted,False)
    assert ledger(65532,'reconcile-delivery',{**accepted,'receipt':'om_'+'d'*32})['state']=='delivered'
    cases.append('actual_controller_uid_requires_exact_native_Feishu_receipt_for_separate_owner_delivered_decision')
    for kind in ['original','webhook']:
        selectors={'profile':'feishu-'+'a'*64,'kind':kind}
        active=raw(65534,'feishu-sources',selectors);entry=active['sources'][0]
        assert active['private_bytes_returned'] is False and entry['purge_allowed'] is False
        permission={**selectors,'id':entry['id'],'snapshot_sha256':entry['snapshot_sha256'],
            'owner_uid':1000,'note_sha256':'e'*64,'confirmed':True}
        raw(65534,'purge-feishu-source',permission,False)
    config['bindings']=[]
    for kind in ['original','webhook']:
        selectors={'profile':'feishu-'+'a'*64,'kind':kind}
        entry=raw(65534,'feishu-sources',selectors)['sources'][0]
        assert entry['purge_allowed'] and entry['stored_bytes']>0
        permission={**selectors,'id':entry['id'],'snapshot_sha256':entry['snapshot_sha256'],
            'owner_uid':1000,'note_sha256':'e'*64,'confirmed':True}
        for uid in [0,65532,65533]:raw(uid,'purge-feishu-source',permission,False)
        first=raw(65534,'purge-feishu-source',permission)
        assert first['removed_payload_bytes']==entry['stored_bytes'] and first['network_requested'] is False
        assert raw(65534,'purge-feishu-source',permission)['removed_payload_bytes']==0
        assert raw(65534,'feishu-sources',selectors)['sources'][0]['purged'] is True
        cases.append('actual_gateway_UID_'+kind+'_source_disposal_requires_withdrawn_grant_retains_tombstone_and_denies_other_UIDs')
    assert canary.read_text()=='preserve-owner-fixture'
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_uids':[0,65532,65533,65534],
        'optional_Hermes_source_or_SDK_imported':False,'network_available':False,
        'prepared_owner_policy_and_metadata_states_are_fixtures':True,'public_Feishu_CLI_GUI_or_live_acceptance':False},indent=2))


if __name__=='__main__':main()
