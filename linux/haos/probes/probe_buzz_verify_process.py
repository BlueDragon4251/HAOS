"""Actual installed SDK helper provenance and UID guards in an offline namespace."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists()
            or os.environ.get('HAOS_DISPOSABLE_BUZZ_VERIFY_PROCESS')!='1' or Path('/usr/lib/haos').exists()
            or Path('/etc/haos').exists() or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit offline Buzz SDK process namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway:/nonexistent:/usr/sbin/nologin\n')
    with Path('/etc/group').open('a') as stream:stream.write('haos-gateway:x:65534:\n')
    target=code/'buzz';target.mkdir(mode=0o755)
    value=json.loads(Path('/public-build/source.json').read_text())
    for name in ['buzz','haos-buzz-verify']:
        shutil.copyfile('/public-bin/'+name,target/name);(target/name).chmod(0o755)
        value['programs'][name]['sha256']=hashlib.sha256((target/name).read_bytes()).hexdigest()
    metadata=target/'source.json';metadata.write_text(json.dumps(value));metadata.chmod(0o644)
    event=json.loads(Path('/public-input/event.json').read_text());cases=[]
    script='''import asyncio,json,os,sys
from haos.gateway_buzz_crypto import verify
try:
    event=asyncio.run(verify(sys.stdin.buffer.read(1048577)))
    print(json.dumps({'verified':True,'id':event['id'],'uid':os.geteuid()}))
except PermissionError:print(json.dumps({'error':'authority-refused'}))
'''
    def run(data,uid=65534,groups=()):
        completed=subprocess.run([sys.executable,'-c',script],input=json.dumps(data),capture_output=True,text=True,
            user=uid,group=65534,extra_groups=list(groups),timeout=15,cwd='/',env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONPATH':str(code)})
        assert completed.returncode==0,completed.stderr
        return json.loads(completed.stdout)
    assert run(event)=={'verified':True,'id':event['id'],'uid':65534}
    cases.append('actual_installed_root_owned_digest_checked_offline_Rust_SDK_helper_executes_only_from_private_gateway_UID_without_secret_environment')
    assert run({**event,'content':'tampered actual source'})=={'error':'authority-refused'}
    cases.append('actual_private_UID_helper_rejects_tampered_signed_event_without_echoing_untrusted_content_or_creating_mission')
    for uid in [0,65533]:assert run(event,uid)=={'error':'authority-refused'}
    cases.append('actual_root_and_agent_UID_cannot_enter_gateway_crypto_service_before_SDK_execution')
    assert run(event,groups=(0,))=={'error':'authority-refused'}
    cases.append('actual_private_UID_with_root_supplementary_group_is_refused_before_SDK_execution')
    helper=target/'haos-buzz-verify';original=helper.read_bytes();helper.write_bytes(original+b'tampered')
    assert run(event)=={'error':'authority-refused'};helper.write_bytes(original)
    cases.append('changed_executable_bytes_are_refused_before_spawn_despite_same_path_owner_and_mode')
    helper.chmod(0o777);assert run(event)=={'error':'authority-refused'};helper.chmod(0o755)
    cases.append('group_or_world_writable_program_is_refused_before_execution')
    linked=target/'helper-hardlink';os.link(helper,linked);assert run(event)=={'error':'authority-refused'};linked.unlink()
    cases.append('multiply_linked_executable_is_refused_before_execution')
    moved=target/'helper-original';helper.rename(moved);helper.symlink_to(moved);assert run(event)=={'error':'authority-refused'};helper.unlink();moved.rename(helper)
    cases.append('symlinked_executable_is_refused_before_execution')
    canary=Path('/private-owner-fixture');canary.write_text('private owner fixture');canary.chmod(0o600)
    denied_code='''from pathlib import Path
for path in ['/usr/lib/haos/buzz/source.json','/usr/lib/haos/buzz/haos-buzz-verify']:
    try:Path(path).write_bytes(b'tampered')
    except PermissionError:continue
    raise AssertionError('unprivileged helper caller altered immutable installed program')
try:Path('/private-owner-fixture').read_bytes()
except PermissionError:pass
else:raise AssertionError('unprivileged caller read owner private file')
print('refused')
'''
    for uid in [65534,65533]:
        denied=subprocess.run([sys.executable,'-c',denied_code],capture_output=True,text=True,user=uid,group=65534,extra_groups=[],timeout=5)
        assert denied.returncode==0 and denied.stdout.strip()=='refused',denied.stderr
    cases.append('actual_gateway_and_agent_UID_cannot_modify_installed_program_or_provenance_or_read_owner_canary')
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_UID_installed_root_owned_code_and_compiled_official_SDK':True,
        'live_relay_ingress_mission_delivery_GUI_or_public_activation':False},indent=2))


if __name__=='__main__':main()
