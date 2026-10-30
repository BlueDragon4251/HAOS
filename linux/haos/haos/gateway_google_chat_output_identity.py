"""Immutable per-output app ownership; metadata never authorizes a new send."""
import json
import re

from .gateway import Conflict,digest

HEX=re.compile('[a-f0-9]{64}\\Z')
NAME=re.compile('[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\\Z')
FIELDS=('id','delivery_id','binding_id','binding_digest','credential_scope','offer_id','size','offer_sha256','sha256','filename','mime')


def fingerprint(row):
    if (any(not isinstance(row[k],str) or not HEX.fullmatch(row[k]) for k in ['id','delivery_id','binding_digest','credential_scope','offer_id','offer_sha256','sha256'])
            or not isinstance(row['binding_id'],str) or not NAME.fullmatch(row['binding_id'])
            or type(row['size']) is not int or not 1<=row['size']<=8*1024*1024
            or row['id']!=digest([row['delivery_id'],row['offer_id']])
            or row['offer_sha256']!=digest({'id':row['offer_id'],'size':row['size'],'sha256':row['sha256']})
            or not isinstance(row['filename'],str) or not re.fullmatch('result-[0-9]{1,6}\\.[a-z0-9]{1,10}',row['filename'])
            or not isinstance(row['mime'],str) or not re.fullmatch('[a-z0-9.+-]+/[a-z0-9.+-]+',row['mime'])):
        raise Conflict('damaged Google output ownership metadata; preserve and inspect')
    return digest({k:row[k] for k in FIELDS})


def prepare(inbox):
    inbox.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_output_owners(
        file_id TEXT PRIMARY KEY,connector TEXT NOT NULL,account_scope TEXT NOT NULL,
        credential_scope TEXT NOT NULL,immutable_sha256 TEXT NOT NULL,evidence_sha256 TEXT NOT NULL)''')


def owner(inbox,row):
    prepare(inbox);entry=inbox.db.execute('SELECT * FROM google_chat_output_owners WHERE file_id=?',(row['id'],)).fetchone()
    if entry is None:return None
    if (not isinstance(entry['connector'],str) or not NAME.fullmatch(entry['connector'])
            or not isinstance(entry['account_scope'],str) or not re.fullmatch('google-chat:[a-f0-9]{64}',entry['account_scope'])
            or entry['credential_scope']!=row['credential_scope'] or entry['immutable_sha256']!=digest([entry['connector'],entry['account_scope'],fingerprint(row)])
            or not isinstance(entry['evidence_sha256'],str) or not HEX.fullmatch(entry['evidence_sha256'])):
        raise Conflict('Google output ownership changed; preserve and inspect')
    return dict(entry)


def retain(inbox,row,connector,account_scope,evidence):
    if (not isinstance(connector,str) or not NAME.fullmatch(connector) or not isinstance(account_scope,str)
            or not re.fullmatch('google-chat:[a-f0-9]{64}',account_scope) or not isinstance(evidence,str) or not HEX.fullmatch(evidence)):
        raise PermissionError('exact verified output app/connector association required')
    proof=digest([connector,account_scope,fingerprint(row)]);old=owner(inbox,row)
    if old is not None:
        if old['connector']!=connector or old['account_scope']!=account_scope:
            raise Conflict('Google output already belongs to another app/connector; never rebind')
        return old
    inbox.db.execute('INSERT INTO google_chat_output_owners VALUES(?,?,?,?,?,?)',
        (row['id'],connector,account_scope,row['credential_scope'],proof,evidence))
    return owner(inbox,row)


def from_file_proof(inbox,operation,proof):
    # Caller has already validated the actual retained FileLedger row/proof.
    if not inbox.db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_output_files'").fetchone():return
    row=inbox.db.execute('SELECT * FROM google_chat_output_files WHERE id=?',(proof['file_id'],)).fetchone()
    if row is None:return
    if (row['delivery_id']!=proof['source']['delivery_id'] or row['binding_id']!=proof['binding_id']
            or row['binding_digest']!=proof['binding_digest'] or row['credential_scope']!=proof['credential_scope']
            or row['sha256']!=proof['file_sha256'] or row['filename']!=proof['filename'] or row['mime']!=proof['mime']):
        raise Conflict('Google retained file proof contradicts its original output identity')
    return retain(inbox,row,proof['connector'],proof['account_scope'],digest(['native-file-proof',operation,digest(proof)]))


def backfill(inbox,policy,connector,account):
    """Legacy metadata only: exact current route or validated retained file proof."""
    from .gateway_google_chat import scope
    prepare(inbox);db=inbox.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_output_files'").fetchone():return
    rows=db.execute('SELECT * FROM google_chat_output_files ORDER BY created_at LIMIT 129').fetchall()
    if len(rows)>128:raise Conflict('Google output custody exceeds existing bounded capacity')
    has_files=db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_file_writes'").fetchone()
    if has_files:
        from .gateway_google_chat_files import FileLedger
        ledger=FileLedger(inbox)
        db.execute("CREATE INDEX IF NOT EXISTS google_chat_file_output_identity ON google_chat_file_writes(json_extract(proof,'$.file_id'),connector,account_scope)")
    for row in rows:
        indexed=db.execute('SELECT connector,account_scope FROM google_chat_output_owners WHERE file_id=?',(row['id'],)).fetchone()
        if indexed is not None:
            if indexed['connector']==connector and indexed['account_scope']==scope(account):owner(inbox,row)
            continue
        try:
            binding=policy.current_binding(dict(row)) if policy is not None else None
            current=(binding is not None and binding['connector']==connector and binding['scope']==scope(account)
                and row['credential_scope']==digest(account))
        except PermissionError:current=False
        if current:
            retain(inbox,row,connector,scope(account),digest(['current-owner-route',row['delivery_id'],row['binding_digest'],row['credential_scope']]))
            continue
        if has_files:
            proofs=db.execute("SELECT id,proof FROM google_chat_file_writes WHERE json_extract(proof,'$.file_id')=? AND connector=? AND account_scope=? LIMIT 2",
                (row['id'],connector,scope(account))).fetchall()
            for item in proofs:
                proof=json.loads(item['proof']);ledger.get(item['id'],proof)
                from_file_proof(inbox,item['id'],proof)


def backfill_identity(inbox,account_scope):
    """Historical indexing uses validated retained file proofs, never guesses."""
    prepare(inbox);db=inbox.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_output_files'").fetchone():return
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_file_writes'").fetchone():return
    from .gateway_google_chat_files import FileLedger
    ledger=FileLedger(inbox)
    db.execute("CREATE INDEX IF NOT EXISTS google_chat_file_output_identity ON google_chat_file_writes(json_extract(proof,'$.file_id'),connector,account_scope)")
    rows=db.execute('SELECT * FROM google_chat_output_files ORDER BY created_at LIMIT 129').fetchall()
    if len(rows)>128:raise Conflict('Google output custody exceeds bounded capacity')
    for row in rows:
        indexed=db.execute('SELECT account_scope FROM google_chat_output_owners WHERE file_id=?',(row['id'],)).fetchone()
        if indexed is not None:
            if indexed['account_scope']==account_scope:owner(inbox,row)
            continue
        proofs=db.execute("SELECT id,proof FROM google_chat_file_writes WHERE json_extract(proof,'$.file_id')=? AND account_scope=? LIMIT 2",
            (row['id'],account_scope)).fetchall()
        for item in proofs:
            proof=json.loads(item['proof']);ledger.get(item['id'],proof);from_file_proof(inbox,item['id'],proof)
