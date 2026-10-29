"""Disposable actual root publication and service-UID email credential custody."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists()
            or os.environ.get('HAOS_DISPOSABLE_EMAIL_PUBLICATION')!='1' or Path('/usr/lib/haos').exists()
            or Path('/etc/haos').exists() or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit disposable email publication container required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    sys.path.insert(0,str(code))
    from haos.gateway_setup import persist,load
    from haos.gateway import GatewayPolicy,digest
    from haos.gateway_email import scope
    config=Path('/etc/haos');config.mkdir(mode=0o755)
    account={'address':'haos@example.invalid','password':'private-mail-fixture',
        'imap_host':'imap.example.invalid','imap_port':993,'imap_security':'tls',
        'smtp_host':'smtp.example.invalid','smtp_port':465,'smtp_security':'tls','authserv_id':'mx.example.invalid'}
    policy={'version':1,'connectors':[{'id':'mail','platform':'email'}],'bindings':[]}
    private={'connectors':{'mail':account}}
    persist(policy,private,config=config,gid=65534)
    assert (config/'gateway-credentials').stat().st_uid==0 and (config/'gateway-credentials').stat().st_mode&0o077==0
    assert (config/'gateways.json').stat().st_uid==0 and (config/'gateways.json').stat().st_gid==65534
    assert (config/'gateways.json').stat().st_mode&0o777==0o640
    cases=['actual_root_publishes_matched_email_account_with_root_private_credentials_and_gateway_group_policy']
    binding={'id':'owner','connector':'mail','sender':'owner@example.invalid','chat':'owner@example.invalid',
        'scope':scope(account),'thread':'<root@example.invalid>','identity':'personal','capabilities':['create','read'],
        'generation':'a'*64,'since':1,'allow_media':True,'allow_outbound_media':True}
    policy['bindings']=[binding];persist(policy,private,config=config,gid=65534)
    approved,_=load(config);first=approved['bindings'][0]
    assert first['generation']!='a'*64 and first['since']>1
    cases.append('actual_owner_publication_assigns_fresh_timed_exact_sender_mailbox_thread_and_separate_media_grants')
    reader='''
import json,os,sys
from pathlib import Path
sys.path.insert(0,'/usr/lib/haos')
from haos.gateway_setup import persist
uid=int(sys.argv[1]);assert os.geteuid()==uid and os.getgroups()==[]
try:Path('/etc/haos/gateway-credentials').read_bytes()
except PermissionError:pass
else:raise AssertionError('service identity read root account password')
try:persist({}, {}, config=Path('/etc/haos'),gid=65534)
except PermissionError:pass
else:raise AssertionError('service identity published an owner grant')
if uid==65534:
 value=json.loads(Path('/etc/haos/gateways.json').read_text());assert value['bindings'][0]['sender']=='owner@example.invalid'
else:
 try:Path('/etc/haos/gateways.json').read_bytes()
 except PermissionError:pass
 else:raise AssertionError('unrelated identity read group-private policy')
'''
    for uid in [65532,65533,65534]:
        child=subprocess.run([sys.executable,'-E','-s','-c',reader,str(uid)],user=uid,group=uid,extra_groups=[],
            capture_output=True,text=True,check=False,timeout=10,cwd='/')
        assert child.returncode==0,child.stderr
    cases.append('actual_gateway_controller_agent_uids_cannot_read_root_credentials_or_publish_owner_authority')
    old_files={name:(config/name).read_bytes() for name in ['gateways.json','gateway-credentials']}
    bad=deepcopy(private);bad['connectors']['mail']['smtp_security']='plain'
    try:persist(approved,bad,config=config,gid=65534)
    except ValueError:pass
    else:raise AssertionError('plaintext SMTP publication accepted')
    assert all((config/name).read_bytes()==raw for name,raw in old_files.items()) and not (config/'gateway-publication.json').exists()
    cases.append('invalid_TLS_account_rejected_before_authority_or_credentials_change')
    retained=Path('/var/lib/haos-email-owner-fixture');retained.mkdir(mode=0o700)
    canary=retained/'owner-recovery';canary.write_bytes(b'preserve-existing-recovery-fixture')
    rotated=deepcopy(private);rotated['connectors']['mail']['password']='rotated-private-mail-fixture'
    persist(approved,rotated,config=config,gid=65534)
    revoked,current=load(config);assert revoked['bindings']==[] and current==rotated
    assert canary.read_bytes()==b'preserve-existing-recovery-fixture'
    cases.append('actual_password_rotation_withdraws_all_old_sender_grants_and_preserves_recovery_data')
    persist(approved,rotated,config=config,gid=65534)
    renewed,_=load(config);second=renewed['bindings'][0]
    assert second['generation']!=first['generation'] and digest(second)!=digest(first)
    assert second['scope']==first['scope'] and GatewayPolicy(renewed).connectors['mail']['platform']=='email'
    cases.append('explicit_repair_after_rotation_gets_new_authority_epoch_and_cannot_resurrect_old_route')
    revoked['connectors']=[];persist(revoked,{'connectors':{}},config=config,gid=65534)
    removed,secrets=load(config);assert removed['connectors']==[] and secrets=={'connectors':{}}
    assert canary.read_bytes()==b'preserve-existing-recovery-fixture'
    cases.append('explicit_account_removal_withdraws_credentials_without_deleting_retained_owner_recovery_data')
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_uids':[0,65532,65533,65534],
        'actual_atomic_root_publication':True,'optional_hermes_sdk_imported':False,'network_available':False,
        'installed_owner_service_or_live_account_acceptance':False},indent=2))


if __name__=='__main__':main()
