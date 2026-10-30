import sqlite3
import time
import pytest

from haos.gateway import Conflict
from haos.gateway_email import PreparedEmailPolicy,scope
from haos.gateway_email_journal import Journal
from haos.gateway_email_recovery import mailboxes,recover_mailbox
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor


@pytest.fixture
def context(tmp_path):
    value={'address':'haos@example.invalid','imap_host':'imap.example.invalid','imap_port':993}
    config={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[{
        'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid','scope':scope(value),
        'thread':'','identity':'personal','capabilities':['create','read'],'generation':'b'*64,'since':1}]}
    inbox=NativeInbox(tmp_path/'native.db',Redactor());journal=Journal(inbox,'email',scope(value),lambda:None)
    journal.observe(77,5)
    journal.commit(journal.page(),[{'uid':1,'header_sha256':'c'*64,'internal_at':time.time()-1,
        'status':'ignored','reason':'unapproved-sender','native_id':None}],uids=[1])
    yield inbox,journal,config
    inbox.close()


def request(inbox):
    row=next(item for item in mailboxes(inbox) if item['active'])
    return {'identity':row['identity'],'snapshot_sha256':row['snapshot_sha256'],'owner_uid':1000,
        'note_sha256':'d'*64,'confirmed':True}


@pytest.mark.parametrize('observed',[(88,3),(77,2)])
def test_owner_recovery_appends_a_new_local_epoch_without_deleting_any_old_cursor_or_receipt(context,observed):
    inbox,journal,config=context;journal.observe(*observed)
    previous=dict(journal.state());receipts=[tuple(row) for row in inbox.db.execute('SELECT * FROM email_receipts')]
    decision=request(inbox);result=recover_mailbox(inbox,PreparedEmailPolicy(config),decision)
    assert result['previous_identity']==previous['identity'] and result['identity']!=previous['identity']
    assert result['old_receipts_preserved'] and not result['grants_changed'] and not result['network_requested']
    assert dict(inbox.db.execute('SELECT * FROM email_mailboxes WHERE identity=?',(previous['identity'],)).fetchone())==previous
    assert [tuple(row) for row in inbox.db.execute('SELECT * FROM email_receipts')]==receipts
    assert inbox.db.execute('SELECT COUNT(*) FROM email_mailbox_owner_events').fetchone()[0]==1
    with pytest.raises(PermissionError):journal.state()
    with pytest.raises(PermissionError):journal.observe(77,10)
    fresh=Journal(inbox,'email',config['bindings'][0]['scope'],lambda:None)
    assert fresh.identity==result['identity'] and fresh.state()['cursor']==0
    assert fresh.page()=={'uid_validity':observed[0],'after':0,'through':observed[1]-1}
    assert len(mailboxes(inbox))==2 and sum(item['active'] for item in mailboxes(inbox))==1
    with pytest.raises(Conflict):recover_mailbox(inbox,PreparedEmailPolicy(config),decision)


def test_changed_server_observations_invalidate_the_inspected_decision(context):
    inbox,journal,config=context;journal.observe(88,3);decision=request(inbox)
    journal.observe(88,4)
    with pytest.raises(Conflict):recover_mailbox(inbox,PreparedEmailPolicy(config),decision)
    assert inbox.db.execute('SELECT COUNT(*) FROM email_mailboxes').fetchone()[0]==1


def test_next_real_connection_must_match_the_accepted_observed_uid_state(context):
    inbox,journal,config=context;journal.observe(88,3)
    recover_mailbox(inbox,PreparedEmailPolicy(config),request(inbox))
    fresh=Journal(inbox,'email',config['bindings'][0]['scope'],lambda:None)
    assert fresh.observe(99,3)['status']=='uid-validity-changed'
    with pytest.raises(PermissionError):fresh.page()


def test_pointer_update_failure_rolls_back_the_new_epoch_and_keeps_all_recovery_data(context):
    inbox,journal,config=context;journal.observe(88,3);before=dict(journal.state())
    inbox.db.execute("CREATE TRIGGER deny_mailbox_pointer BEFORE UPDATE ON email_mailbox_current BEGIN SELECT RAISE(FAIL,'fixture pointer failure'); END")
    with pytest.raises(sqlite3.IntegrityError):recover_mailbox(inbox,PreparedEmailPolicy(config),request(inbox))
    assert journal.state()==before and inbox.db.execute('SELECT COUNT(*) FROM email_mailboxes').fetchone()[0]==1
    assert inbox.db.execute('SELECT COUNT(*) FROM email_receipts').fetchone()[0]==1


@pytest.mark.parametrize('change',[{'confirmed':False},{'owner_uid':True},{'note_sha256':'bad'},
    {'snapshot_sha256':'0'*64},{'extra':'plugin-field'}])
def test_unconfirmed_malformed_or_stale_mailbox_decision_cannot_change_state(context,change):
    inbox,journal,config=context;journal.observe(88,3);before=dict(journal.state())
    with pytest.raises((PermissionError,ValueError,Conflict)):
        recover_mailbox(inbox,PreparedEmailPolicy(config),{**request(inbox),**change})
    assert journal.state()==before


def test_unfenced_or_other_scope_mailbox_cannot_be_recovered(context):
    inbox,journal,config=context
    with pytest.raises(Conflict):recover_mailbox(inbox,PreparedEmailPolicy(config),request(inbox))
    journal.observe(88,3);config['bindings'][0]['scope']='mailbox:'+'f'*64
    with pytest.raises(PermissionError):recover_mailbox(inbox,PreparedEmailPolicy(config),request(inbox))
    assert inbox.db.execute('SELECT COUNT(*) FROM email_receipts').fetchone()[0]==1


def test_preceding_mailbox_schema_gains_a_pointer_without_rewriting_its_history(context):
    inbox,journal,config=context;journal.observe(88,3);decision=request(inbox)
    original=[tuple(row) for row in inbox.db.execute('SELECT * FROM email_mailboxes')]
    inbox.db.execute('DROP TABLE email_mailbox_current')  # Disposable preceding-schema fixture only.
    result=recover_mailbox(inbox,PreparedEmailPolicy(config),decision)
    assert result['identity']!=decision['identity']
    assert [tuple(row) for row in inbox.db.execute('SELECT * FROM email_mailboxes WHERE identity=?',(decision['identity'],))]==original
    assert inbox.db.execute('SELECT COUNT(*) FROM email_receipts').fetchone()[0]==1


def intent(inbox,state='uncertain'):
    from haos.gateway_email_recovery import outgoing
    inbox.db.execute('''CREATE TABLE IF NOT EXISTS email_delivery_intents(
        delivery_id TEXT NOT NULL,attempt INTEGER NOT NULL,fingerprint TEXT NOT NULL,state TEXT NOT NULL,
        receipt TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(delivery_id,attempt))''')
    inbox.db.execute('INSERT INTO email_delivery_intents VALUES(?,?,?,?,?,?,?)',
        ('e'*64,1,'f'*64,state,'smtp_accept_'+'c'*64 if state=='confirmed' else '',int(time.time()),time.time()))
    row=outgoing(inbox)[0]
    return {'connector':'email','delivery_id':row['delivery_id'],'attempt':row['attempt'],
        'snapshot_sha256':row['snapshot_sha256'],'owner_uid':1000,'note_sha256':'d'*64,
        'confirmed':True,'confirmed_not_delivered':True}


def test_offline_owner_retry_is_audited_idempotent_and_does_not_send_or_reconcile_controller(context):
    from haos.gateway_email_recovery import approve_retry,outgoing
    inbox,_journal,config=context;inspection=intent(inbox)
    result=approve_retry(inbox,PreparedEmailPolicy(config),inspection)
    assert result['private_retry_approved'] and result['controller_reconciliation_still_required'] and not result['network_requested']
    assert outgoing(inbox)[0]['state']=='owner-retry-approved'
    assert approve_retry(inbox,PreparedEmailPolicy(config),inspection)==result
    assert inbox.db.execute('SELECT COUNT(*) FROM email_delivery_owner_events').fetchone()[0]==1
    with pytest.raises(Conflict):approve_retry(inbox,PreparedEmailPolicy(config),{**inspection,'note_sha256':'a'*64})


@pytest.mark.parametrize('change',[{'confirmed_not_delivered':False},{'confirmed':False},{'attempt':5},
    {'snapshot_sha256':'0'*64},{'connector':'unknown'}])
def test_unknown_or_uninspected_smtp_write_cannot_gain_an_owner_retry_permission(context,change):
    from haos.gateway_email_recovery import approve_retry,outgoing
    inbox,_journal,config=context;inspection=intent(inbox)
    with pytest.raises((PermissionError,ValueError,Conflict)):
        approve_retry(inbox,PreparedEmailPolicy(config),{**inspection,**change})
    assert outgoing(inbox)[0]['state']=='uncertain'


def test_confirmed_acceptance_is_never_released_for_duplicate_write_even_by_non_delivery_claim(context):
    from haos.gateway_email_recovery import approve_retry,outgoing
    inbox,_journal,config=context;inspection=intent(inbox,'confirmed')
    with pytest.raises(PermissionError):approve_retry(inbox,PreparedEmailPolicy(config),inspection)
    assert outgoing(inbox)[0]['state']=='confirmed' and outgoing(inbox)[0]['recipient_receipt_verified'] is False


def test_owner_authentication_recheck_preserves_backoff_mailbox_fence_and_other_statuses(context):
    from haos.gateway_raw_recovery import retry_email_auth
    inbox,journal,config=context;journal.observe(88,3)
    inbox.db.execute('''CREATE TABLE email_profile_status(identity TEXT PRIMARY KEY,connector TEXT NOT NULL,
        credential_scope TEXT NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL,next_attempt REAL NOT NULL)''')
    deadline=time.time()+600
    for index,state in enumerate(['smtp-authentication-refused','rate-limited','uid-state-changed','revoked']):
        inbox.db.execute('INSERT INTO email_profile_status VALUES(?,?,?,?,?,?)',(str(index),'email','a'*64,state,time.time(),deadline))
    result=retry_email_auth(inbox,PreparedEmailPolicy(config),{'connector':'email','owner_uid':1000,'note_sha256':'d'*64})
    assert result['authentication_blocks_cleared']==1 and not result['network_requested']
    assert [row[0] for row in inbox.db.execute('SELECT status FROM email_profile_status ORDER BY identity')]==['created','rate-limited','uid-state-changed','revoked']
    assert all(row[0]==deadline for row in inbox.db.execute('SELECT next_attempt FROM email_profile_status'))
    assert journal.state()['status']=='uid-validity-changed'
    assert inbox.db.execute('SELECT COUNT(*) FROM email_owner_events').fetchone()[0]==1
