"""Disposable real-UID offline email recovery; never an installed owner shortcut."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists()
            or os.environ.get('HAOS_DISPOSABLE_EMAIL_RECOVERY')!='1' or Path('/usr/lib/haos').exists()
            or Path('/etc/haos').exists() or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit offline email recovery container required')
    installed=Path('/usr/lib/haos');installed.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(installed/'haos')],check=True)
    with Path('/etc/passwd').open('a') as stream:
        stream.write('haos-gateway:x:65534:65534:Disposable private gateway:/nonexistent:/usr/sbin/nologin\n')
        stream.write('haos-control:x:65532:65532:Disposable private controller:/nonexistent:/usr/sbin/nologin\n')
    for name,uid in [('haos-gateway',65534),('haos-control',65532)]:
        state=Path('/var/lib')/name;state.mkdir(mode=0o700);os.chown(state,uid,uid)
    temporary=Path(tempfile.mkdtemp(prefix='haos-email-owner-'));temporary.chmod(0o755)
    owner=temporary/'owner-canary';owner.write_text('preserve-existing-owner-fixture');owner.chmod(0o600)
    sys.path.insert(0,str(installed))
    from haos.gateway_email import scope
    config={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[{
        'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid',
        'scope':scope({'address':'haos@example.invalid','imap_host':'imap.example.invalid','imap_port':993}),
        'thread':'','identity':'personal','capabilities':['create','read'],'generation':'b'*64,'since':1}]}
    seed=temporary/'seed.py';seed.write_text('''
import asyncio,hashlib,json,os,sys,time
from pathlib import Path
sys.path.insert(0,'/usr/lib/haos')
from haos.gateway import digest,GatewayEngine
from haos.gateway_email import PreparedEmailPolicy
from haos.gateway_email_journal import Journal
from haos.gateway_email_cache import RawCache
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
request=json.load(sys.stdin);policy=PreparedEmailPolicy(request['policy']);binding=policy.bindings['owner']
assert os.getgroups()==[]
try:Path(request['canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('service identity read owner data')
envelope={'platform':'email','sender':binding['sender'],'chat':binding['chat'],'scope':binding['scope'],'thread':'',
    'message_id':'c'*64,'is_bot':False,'text':'A controlled recovery fixture goal.'}
if os.geteuid()==65532:
    from haos.store import MissionStore
    store=MissionStore(Path('/var/lib/haos-control/missions.db'));engine=GatewayEngine(store)
    asyncio.run(engine.receive(policy,'email',envelope,None));delivery=engine.next_delivery(policy)
    print(json.dumps({'delivery_id':delivery['id'],'attempt':delivery['attempt']}));store.close()
else:
    assert os.geteuid()==65534
    root=Path('/var/lib/haos-gateway');profiles=root/'profiles';profiles.mkdir(mode=0o700)
    profile=profiles/('email-'+'a'*64);profile.mkdir(mode=0o700)
    inbox=NativeInbox(root/'native-inbox.db',Redactor());cache=RawCache(profile/'raw.db',Redactor())
    raw=b'From: owner@example.invalid'+bytes([13,10,13,10])+b'A private recovery source.'
    stamp=time.time()-1;header=raw[:raw.index(bytes([13,10,13,10]))+4]
    resource={'uid':1,'uid_validity':77,'uid_next':4,'internal_at':stamp,'size':len(raw),'content':raw,'sha256':hashlib.sha256(raw).hexdigest(),
        'approval':{'binding_id':'owner','binding_digest':digest(binding),'received_at':stamp,'header_sha256':hashlib.sha256(header).hexdigest(),
            'rfc_message_id':'<recovery@example.invalid>','envelope':{**envelope,'text':''}}}
    identity=cache.put(policy,'email',resource);key=inbox.admit(policy,'email',envelope,{'raw_id':identity},received_at=stamp)
    journal=Journal(inbox,'email',binding['scope'],lambda:None);journal.observe(77,4);journal.remember_capture(key)
    journal.commit(journal.page(),[{'uid':1,'header_sha256':resource['approval']['header_sha256'],'internal_at':stamp,
        'status':'captured','reason':'','native_id':key}],uids=[1]);journal.observe(88,2)
    inbox.db.execute('CREATE TABLE email_profile_status(identity TEXT PRIMARY KEY,connector TEXT,credential_scope TEXT,status TEXT,updated_at REAL,next_attempt REAL)')
    inbox.db.execute('INSERT INTO email_profile_status VALUES(?,?,?,?,?,?)',('f'*64,'email','e'*64,'smtp-authentication-refused',time.time(),time.time()+600))
    inbox.db.execute('CREATE TABLE email_delivery_intents(delivery_id TEXT,attempt INTEGER,fingerprint TEXT,state TEXT,receipt TEXT,created_at INTEGER,updated_at REAL,PRIMARY KEY(delivery_id,attempt))')
    inbox.db.execute('INSERT INTO email_delivery_intents VALUES(?,?,?,?,?,?,?)',(request['delivery_id'],1,'f'*64,'uncertain','',int(time.time()),time.time()))
    print(json.dumps({'ingress_id':key,'raw_id':identity,'profile':profile.name}));cache.close();inbox.close()
''');seed.chmod(0o644)
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'};cases=[]
    def execute(uid,args,value,*,accepted=True):
        result=subprocess.run([sys.executable,'-E','-s',*args],input=json.dumps(value),text=True,capture_output=True,
            timeout=15,user=uid,group=uid,extra_groups=[],umask=0o077,cwd=installed,env=env)
        if not accepted:
            assert result.returncode!=0 and len(result.stderr)<8192;return None
        assert result.returncode==0,result.stderr[-2000:]
        assert len(result.stdout)<256*1024
        return json.loads(result.stdout)
    control=execute(65532,[str(seed)],{'policy':config,'canary':str(owner)})
    gateway=execute(65534,[str(seed)],{'policy':config,'canary':str(owner),**control})
    def raw(uid,action,params,**kwargs):return execute(uid,['-m','haos.gateway_raw_recovery'],{'action':action,'policy':config,'params':params},**kwargs)
    def ledger(uid,action,params,**kwargs):return execute(uid,['-m','haos.gateway_recovery'],{'action':action,'policy':config,'params':params},**kwargs)
    for uid in [0,65532,65533]:raw(uid,'ingress',{'after':0},accepted=False)
    for uid in [0,65533,65534]:ledger(uid,'deliveries',{'after':0},accepted=False)
    cases.append('actual_agent_root_and_other_service_uids_cannot_open_the_wrong_offline_helper_despite_supplied_owner_fields')
    status=raw(65534,'ingress',{'after':0});assert status['ingress'][0]['platform']=='email'
    mailbox=next(row for row in status['email_mailboxes'] if row['active']);assert mailbox['status']=='uid-validity-changed'
    deadline=status['transport'][0]['next_attempt']
    assert raw(65534,'retry-email-auth',{'connector':'email','owner_uid':1000,'note_sha256':'d'*64})['authentication_blocks_cleared']==1
    current=raw(65534,'ingress',{'after':0});assert current['transport'][0]['status']=='created' and current['transport'][0]['next_attempt']==deadline
    assert current['email_mailboxes'][0]['status']=='uid-validity-changed'
    cases.append('actual_gateway_uid_authentication_recheck_preserves_retry_deadline_and_mailbox_fence_without_sdk_or_network')
    decision={'identity':mailbox['identity'],'snapshot_sha256':mailbox['snapshot_sha256'],'owner_uid':1000,'note_sha256':'d'*64,'confirmed':True}
    recovered=raw(65534,'recover-email-mailbox',decision);assert recovered['old_receipts_preserved'] and not recovered['network_requested']
    raw(65534,'recover-email-mailbox',decision,accepted=False)
    current=raw(65534,'ingress',{'after':0});assert len(current['email_mailboxes'])==2
    assert next(row for row in current['email_mailboxes'] if row['active'])['cursor']==0
    cases.append('actual_gateway_uid_owner_mailbox_recovery_appends_epoch_preserves_history_and_refuses_stale_replay')
    index=raw(65534,'email-sources',{'profile':None});assert index['profiles'][0]['profile']==gateway['profile']
    source=raw(65534,'email-sources',{'profile':gateway['profile']})['sources'][0];assert not source['purge_allowed']
    purge={'profile':gateway['profile'],'id':gateway['raw_id'],'snapshot_sha256':source['snapshot_sha256'],
        'owner_uid':1000,'note_sha256':'d'*64,'confirmed':True}
    raw(65534,'purge-email-source',purge,accepted=False)
    cases.append('actual_gateway_uid_inventory_uses_opaque_profile_and_refuses_pending_source_purge')
    raw(65534,'reconcile-ingress',{'ingress_id':gateway['ingress_id'],'attempt':0,'state':'pending','decision':'discard','owner_uid':1000,'note_sha256':'d'*64})
    source=raw(65534,'email-sources',{'profile':gateway['profile']})['sources'][0];purge['snapshot_sha256']=source['snapshot_sha256']
    assert raw(65534,'purge-email-source',purge)['removed_payload_bytes']>0
    assert raw(65534,'purge-email-source',purge)['removed_payload_bytes']==0
    assert raw(65534,'email-sources',{'profile':gateway['profile']})['sources'][0]['state']=='purged'
    cases.append('actual_gateway_uid_explicit_discard_and_inspected_purge_retain_receipt_tombstone_and_idempotent_audit')
    intent=current['native_outgoing'][0]
    permission={'connector':'email','delivery_id':control['delivery_id'],'attempt':1,'snapshot_sha256':intent['snapshot_sha256'],
        'owner_uid':1000,'note_sha256':'d'*64,'confirmed':True,'confirmed_not_delivered':True}
    assert raw(65534,'approve-email-retry',permission)['controller_reconciliation_still_required']
    assert ledger(65532,'deliveries',{'after':0})['deliveries'][0]['state']=='sending'
    assert ledger(65532,'reconcile-delivery',{'delivery_id':control['delivery_id'],'attempt':1,'decision':'retry',
        'owner_uid':1000,'note_sha256':'d'*64,'receipt':None,'confirmed_not_delivered':True})['state']=='pending'
    cases.append('distinct_gateway_and_controller_uids_record_separate_owner_retry_decisions_without_sending_or_rewriting_prior_intent')
    assert owner.read_text()=='preserve-existing-owner-fixture'
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_uids':[0,65532,65533,65534],
        'prepared_email_policy_and_owner_service_control_are_fixtures':True,'optional_hermes_sdk_imported':False,
        'network_available':False,'external_messages_or_installed_owner_acceptance':False},indent=2))


if __name__=='__main__':main()
