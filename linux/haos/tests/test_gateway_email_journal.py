import time
import pytest

from haos.gateway import Conflict
from haos.gateway_email import PreparedEmailPolicy,scope
from haos.gateway_email_journal import Journal
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor


@pytest.fixture
def mailbox(tmp_path):
    inbox=NativeInbox(tmp_path/'native.db',Redactor());allowed=[True]
    def current():
        if not allowed[0]:raise PermissionError('owner publication withdrawn')
    source='mailbox:'+'a'*64;journal=Journal(inbox,'email',source,current)
    yield inbox,journal,allowed
    inbox.close()


def outcome(uid=1,**change):
    return {'uid':uid,'header_sha256':'b'*64,'internal_at':time.time()-1,'status':'ignored',
        'reason':'unapproved-sender','native_id':None,**change}


def test_initial_mailbox_does_not_skip_existing_messages_and_empty_ranges_commit(mailbox):
    inbox,journal,allowed=mailbox
    state=journal.observe(77,2001);assert state['cursor']==0
    page=journal.page();assert page=={'uid_validity':77,'after':0,'through':1000}
    journal.commit(page,[],uids=[]);assert journal.state()['cursor']==1000
    journal.commit(journal.page(),[outcome(1500)],uids=[1500])
    assert journal.page() is None
    assert inbox.db.execute('SELECT COUNT(*) FROM email_receipts').fetchone()[0]==1


@pytest.mark.parametrize('reset',[(88,4),(77,2)])
def test_mailbox_reset_or_uidnext_regression_fences_without_deleting_receipts_or_auto_reenabling(mailbox,reset):
    inbox,journal,allowed=mailbox;journal.observe(77,5);journal.commit(journal.page(),[outcome()],uids=[1])
    journal.observe(*reset)
    with pytest.raises(PermissionError):journal.page()
    journal.observe(77,10)
    with pytest.raises(PermissionError):journal.page()
    assert journal.state()['cursor']==4 and journal.state()['uid_validity']==77
    assert inbox.db.execute('SELECT COUNT(*) FROM email_receipts').fetchone()[0]==1


def test_stale_page_and_changed_owner_cannot_advance_or_add_receipts(mailbox):
    inbox,journal,allowed=mailbox;journal.observe(77,4);page=journal.page()
    allowed[0]=False
    with pytest.raises(PermissionError):journal.commit(page,[outcome()],uids=[1])
    assert inbox.db.execute('SELECT cursor FROM email_mailboxes').fetchone()[0]==0
    allowed[0]=True;journal.commit(page,[outcome()],uids=[1])
    with pytest.raises(Conflict):journal.commit(page,[outcome()],uids=[1])
    assert inbox.db.execute('SELECT COUNT(*) FROM email_receipts').fetchone()[0]==1


def test_audit_storage_failure_rolls_back_receipts_and_cursor_together(mailbox):
    inbox,journal,allowed=mailbox;journal.observe(77,4)
    inbox.db.execute("CREATE TRIGGER fixture_storage_fault BEFORE UPDATE OF cursor ON email_mailboxes BEGIN SELECT RAISE(ABORT,'fixture storage failure'); END")
    with pytest.raises(__import__('sqlite3').IntegrityError):journal.commit(journal.page(),[outcome()],uids=[1])
    assert journal.state()['cursor']==0 and inbox.db.execute('SELECT COUNT(*) FROM email_receipts').fetchone()[0]==0


def test_mailbox_cursor_needs_native_durable_capture_and_scope_survives_compaction(mailbox):
    inbox,journal,allowed=mailbox;journal.observe(77,4)
    with pytest.raises(PermissionError):journal.commit(journal.page(),[outcome(status='captured',reason='',native_id='c'*64)],uids=[1])
    policy=PreparedEmailPolicy({'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[{
        'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid','scope':journal.scope,
        'thread':'','identity':'personal','capabilities':['create'],'generation':'d'*64,'since':1}]})
    event={'platform':'email','sender':'owner@example.invalid','chat':'owner@example.invalid','scope':journal.scope,
        'thread':'','message_id':'e'*64,'is_bot':False,'text':'A durably retained email goal'}
    identity=inbox.admit(policy,'email',event,{'raw_id':'f'*64})
    journal.remember_capture(identity);assert inbox.claim(identity,policy)
    inbox.complete(identity,True)
    assert inbox.db.execute('SELECT envelope FROM native_inbox').fetchone()[0]=='{}'
    journal.commit(journal.page(),[outcome(status='captured',reason='',native_id=identity)],uids=[1])
    foreign=Journal(inbox,'email','mailbox:'+'9'*64,lambda:None);foreign.observe(77,4)
    with pytest.raises(PermissionError):foreign.commit(foreign.page(),[outcome(status='captured',reason='',native_id=identity)],uids=[1])
    assert foreign.state()['cursor']==0


def test_cursor_cannot_skip_a_searched_uid_without_a_durable_disposition(mailbox):
    inbox,journal,allowed=mailbox;journal.observe(77,4)
    with pytest.raises(ValueError):journal.commit(journal.page(),[outcome()],uids=[1,2])
    assert journal.state()['cursor']==0 and inbox.db.execute('SELECT COUNT(*) FROM email_receipts').fetchone()[0]==0
    missing=outcome(2,status='refused',reason='source-unavailable',header_sha256=None,internal_at=None)
    journal.commit(journal.page(),[outcome(),missing],uids=[1,2])
    row=inbox.db.execute('SELECT header_sha256,internal_at,status FROM email_receipts WHERE uid=2').fetchone()
    assert tuple(row)==(None,None,'refused')
    assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==0
