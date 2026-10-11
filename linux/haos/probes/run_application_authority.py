"""Real root-to-controller UID/WAL boundary in an offline disposable container."""
import json
import hashlib
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid


def main():
    if (os.geteuid() != 0 or os.environ.get('HAOS_DISPOSABLE_APPLICATION_TEST') != '1'
            or not Path('/.dockerenv').is_file() or not os.statvfs('/').f_flag & os.ST_RDONLY
            or set(p.name for p in Path('/sys/class/net').iterdir()) != {'lo'}):
        raise PermissionError('explicit read-only offline disposable root fixture required')
    sys.path.insert(0, '/usr/lib/haos')
    from haos.application_launcher import running_mission
    account = pwd.getpwnam('nobody')
    root = Path(tempfile.mkdtemp(prefix='haos-app-ledger-'))
    root.chmod(0o755)
    ledger = root / 'controller'; ledger.mkdir(mode=0o700)
    os.chown(ledger, account.pw_uid, account.pw_gid)
    database = ledger / 'missions.db'
    mission = str(uuid.uuid4())
    def controller(code):
        def identity():
            os.setgroups([]); os.setgid(account.pw_gid); os.setuid(account.pw_uid)
        return subprocess.run(['/usr/bin/python3', '-I', '-c', code, str(database), mission],
            preexec_fn=identity, env={'PATH':'/usr/bin:/bin'}, check=True, timeout=5)
    def denied(path=database):
        try: running_mission(path, mission, account.pw_uid)
        except PermissionError: return
        raise AssertionError('invalid mission authority accepted')
    try:
        controller("import sqlite3,sys,time,os; d=sqlite3.connect(sys.argv[1]); "
            "d.execute('PRAGMA journal_mode=WAL'); "
            "d.execute('CREATE TABLE missions (id TEXT,state TEXT,phase TEXT,session_id TEXT,cancel_requested INTEGER,deadline REAL)'); "
            "d.execute('INSERT INTO missions VALUES(?,?,?,?,?,?)',(sys.argv[2],'running','dispatching','offline-authority-fixture',0,time.time()+60)); "
            "d.commit();os.chmod(sys.argv[1],0o600)")
        running_mission(database, mission, account.pw_uid)
        controller("import sqlite3,sys; d=sqlite3.connect(sys.argv[1]); d.execute('UPDATE missions SET cancel_requested=1');d.commit()")
        denied()
        controller("import sqlite3,sys; d=sqlite3.connect(sys.argv[1]);d.execute('UPDATE missions SET cancel_requested=0,deadline=1');d.commit()")
        denied()
        alias=ledger/'alias.db'; alias.symlink_to(database); denied(alias); alias.unlink()
        controller("import os,sys;os.chmod(sys.argv[1],0o644)"); denied()
        controller("import os,sys;os.chmod(sys.argv[1],0o600)")
        # Even a controller-selected SQLite alias cannot make the root broker
        # open its private authority/credential paths. Only allow/deny crosses.
        secret=root/'owner-private';secret.mkdir(mode=0o700)
        (secret/'never-read.db').write_text('fixed disposable owner canary')
        database.unlink(); database.symlink_to(secret/'never-read.db'); denied()
        print(json.dumps({'scope':'disposable root/controller authority component',
            'source_commit':os.environ.get('GITHUB_SHA'),
            'launcher_sha256':hashlib.sha256(Path('/usr/lib/haos/haos/application_launcher.py').read_bytes()).hexdigest(),
            'real_fork_uid_wal_admission':True,'cancelled_mission_denied':True,
            'expired_mission_denied':True,'aliases_and_public_ledger_denied':True,
            'root_private_path_substitution_denied':True,
            'installed_application_unit_verified':False}),flush=True)
    finally:
        shutil.rmtree(root)


if __name__=='__main__': main()
