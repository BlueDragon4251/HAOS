"""Actual independent root nonce persistence in an offline disposable container."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid


def main():
    if (os.geteuid()!=0 or os.environ.get('HAOS_DISPOSABLE_APPLICATION_TEST')!='1'
            or not Path('/.dockerenv').is_file() or not os.statvfs('/').f_flag&os.ST_RDONLY
            or set(p.name for p in Path('/sys/class/net').iterdir())!={'lo'}):
        raise PermissionError('explicit offline disposable root fixture required')
    mounts=Path('/proc/self/mountinfo').read_text().splitlines()
    if not any(line.split()[4]=='/run' and ' - tmpfs ' in line for line in mounts):
        raise PermissionError('own disposable authority tmpfs required')
    sys.path.insert(0,'/usr/lib/haos')
    from haos.application_authority import ActionNonces
    root=Path(tempfile.mkdtemp(prefix='haos-nonces-',dir='/run'));root.chmod(0o700)
    path=root/'actions.db';db=None
    mission=str(uuid.uuid4());key=str(uuid.uuid4());action={'operation':'app.start','program':'approved-terminal'}
    try:
        db=ActionNonces(path);db.admit(key,mission,action)
        assert db.db.execute('SELECT state FROM actions WHERE id=?',(key,)).fetchone()[0]=='admitted'
        assert db.db.execute('SELECT COUNT(*) FROM actions').fetchone()[0]==1
        db.close();db=ActionNonces(path)
        assert db.db.execute('SELECT state FROM actions WHERE id=?',(key,)).fetchone()[0]=='uncertain'
        for value in (action,dict(action,program='changed-approval')):
            try:db.admit(key,mission,value)
            except PermissionError:pass
            else:raise AssertionError('restarted admission may not re-dispatch any action')
        second=str(uuid.uuid4());db.admit(second,mission,action);db.settle(second,'succeeded')
        try:db.admit(second,mission,action)
        except PermissionError:pass
        else:raise AssertionError('completed action replay accepted')
        assert path.stat().st_uid==0 and path.stat().st_mode&0o777==0o600
        assert 'approved-terminal' not in json.dumps(db.db.execute('SELECT * FROM actions').fetchall())
        db.close();db=None
        alias=root/'alias.db';alias.symlink_to(path)
        try:ActionNonces(alias)
        except PermissionError:pass
        else:raise AssertionError('aliased authority store accepted')
        print(json.dumps({'scope':'actual offline independent application nonce persistence',
            'source_commit':os.environ.get('GITHUB_SHA'),'durable_admission_before_dispatch':True,
            'restart_marks_uncertain_without_replay':True,'changed_payload_replay_denied':True,
            'completed_nonce_replay_denied':True,'private_root_nonce_permissions':True,
            'no_arguments_or_pixels_in_nonce_store':True,'aliased_nonce_store_denied':True}),flush=True)
    finally:
        if db:db.close()
        shutil.rmtree(root)


if __name__=='__main__':main()
