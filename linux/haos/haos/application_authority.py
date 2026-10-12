"""Independent application admission/revocation, underneath the existing GUI queue.

Only the controller's committed action is accepted. Root records a nonce before
any input or launch; a lost receipt is never a reason to repeat that action.
"""
import json
import os
from pathlib import Path
import sqlite3
import stat
import time

from .application_launcher import ApplicationLauncher,canonical_id,grant_digest,running_mission
from .application_protocol import action as validate_action,action_digest,receipt
from .enrollment import protected_directory


class ActionNonces:
    def __init__(self,path):
        self.require_root()
        self.path=Path(path);protected_directory(self.path.parent)
        if not self.path.exists() and not self.path.is_symlink():
            fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            os.fsync(fd);os.close(fd)
            directory=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:os.fsync(directory)
            finally:os.close(directory)
        info=self.path.lstat()
        if (self.path.resolve()!=self.path or not stat.S_ISREG(info.st_mode) or info.st_uid!=0
                or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600):
            raise PermissionError('private independent application nonce store required')
        self.db=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,isolation_level=None,timeout=1)
        self.db.execute('PRAGMA trusted_schema=OFF');self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY,mission TEXT NOT NULL,operation TEXT NOT NULL,sha256 TEXT NOT NULL,state TEXT NOT NULL,created_at REAL NOT NULL)')
        # Never turn an interrupted admission into a pending/replayable action.
        self.db.execute("UPDATE actions SET state='uncertain' WHERE state='admitted'")

    @staticmethod
    def require_root():
        if os.geteuid()!=0:raise PermissionError('independent application authority required')

    def admit(self,key,mission,action):
        self.require_root();canonical_id(key);canonical_id(mission);action=validate_action(action)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute('SELECT COUNT(*) FROM actions').fetchone()[0]>=20000:
                raise PermissionError('independent application admission budget exhausted')
            if self.db.execute('SELECT COUNT(*) FROM actions WHERE mission=?',(mission,)).fetchone()[0]>=1024:
                raise PermissionError('independent mission application action budget exhausted')
            self.db.execute('INSERT INTO actions VALUES(?,?,?,?,?,?)',(key,mission,action['operation'],action_digest(action),'admitted',time.time()))
            self.db.execute('COMMIT')
        except BaseException as exc:
            self.db.execute('ROLLBACK')
            if isinstance(exc,sqlite3.IntegrityError):
                raise PermissionError('application action already admitted; reconcile before retrying') from None
            raise

    def settle(self,key,state):
        self.require_root();canonical_id(key)
        if state not in {'succeeded','uncertain'}:raise ValueError('invalid independent action settlement')
        row=self.db.execute("UPDATE actions SET state=? WHERE id=? AND state='admitted'",(state,key))
        if row.rowcount!=1:raise PermissionError('application action has no unsettled admission')

    def close(self):
        self.require_root();self.db.close()


class ApplicationAuthority:
    def __init__(self,launcher,nonces,ledger,controller_uid):
        ActionNonces.require_root()
        self.launcher,self.nonces,self.ledger,self.controller_uid=launcher,nonces,Path(ledger),controller_uid

    def dispatch(self,request):
        ActionNonces.require_root()
        if not isinstance(request,dict) or set(request)!={'id','mission','action'}:
            raise PermissionError('closed mission application request required')
        key,mission=canonical_id(request['id']),canonical_id(request['mission'])
        action=validate_action(request['action'])
        running_mission(self.ledger,mission,self.controller_uid,request=key,action=action)
        # Validate instance ownership *before* admitting a side effect. The
        # root nonce and recheck both precede the actual compositor input.
        op=action['operation']
        if op not in {'app.start','app.catalog'}:
            record=self.launcher.record(action['instance'])
            if record['mission']!=mission or record['state']!='submitted':
                raise PermissionError('application instance belongs to another mission or has stopped')
        self.nonces.admit(key,mission,action)
        try:
            running_mission(self.ledger,mission,self.controller_uid,request=key,action=action)
            if op=='app.catalog':
                # Owner-approved metadata only, never fixed arguments, paths,
                # environment or credentials. Launch separately verifies actual
                # executable bytes; listing an approval is not runtime evidence.
                result={'programs':[{'program':grant['id'],'class':grant['class'],
                    'approved_sha256':grant['sha256'],'memory_mib':grant['memory_mib'],
                    'runtime_seconds':grant['runtime_seconds']}
                    for grant in self.launcher.registry.read()['applications']]}
            elif op=='app.start':
                result=self.launcher.start(action['program'],mission,key,ledger=self.ledger,ledger_uid=self.controller_uid)
                result={'instance':result['request'],'program':result['application'],'state':result['state']}
            elif op=='app.close':
                result=self.launcher.stop(action['instance']);result={'instance':result['request'],'state':result['state']}
            else:
                args={'operation':op.removeprefix('app.'),**{k:v for k,v in action.items() if k not in {'operation','instance'}}}
                result=self.launcher.execute(action['instance'],mission,args,ledger=self.ledger,ledger_uid=self.controller_uid)
                result={'instance':action['instance'],**result}
            result=receipt(op,result)
            self.nonces.settle(key,'succeeded')
            return result
        except BaseException:
            self.nonces.settle(key,'uncertain')
            raise

    def reconcile(self,*,restart=False):
        """Independent owner/mission revocation; no renderer heartbeat required."""
        ActionNonces.require_root()
        stopped=[]
        for path in self.launcher.state.iterdir():
            record=self.launcher.record(path.stem)
            if record['state']=='stopped':continue
            revoke=restart
            if not revoke:
                try:
                    running_mission(self.ledger,record['mission'],self.controller_uid)
                    if grant_digest(self.launcher.registry.resolve(record['application']))!=record['grant_sha256']:
                        revoke=True
                    unit=self.launcher.unit_state(record['request'])
                    if unit['ActiveState'] in {'inactive','failed'} and unit['MainPID']=='0':revoke=True
                except (PermissionError,KeyError,ValueError,OSError,sqlite3.Error):revoke=True
            if revoke:
                self.launcher.stop(record['request']);stopped.append(record['request'])
        return stopped
