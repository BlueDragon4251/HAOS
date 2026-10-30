"""Local observation metadata custody is separate from sender authorization."""
import json
import time
from copy import deepcopy
import pytest
from haos.gateway import Conflict,digest
from haos.gateway_dingtalk_pairing import Candidates,challenge,candidate
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_dingtalk import account


def request():
    now=int(time.time()*1000)
    return {'nonce':'a'*32,'since':now-1000,'until':now+60000}


@pytest.mark.parametrize('change',[{'nonce':'short'},{'nonce':'A'*32},{'since':True},{'until':2**53},{'extra':True}])
def test_malformed_observation_never_uses_optional_sdk(change):
    with pytest.raises((ValueError,PermissionError)):candidate(account(),{**request(),**change},b'{}')


def test_nonchallenge_is_neither_candidate_nor_implicit_grant():
    assert candidate(account(),request(),b'{"msgtype":"text","text":{"content":"ordinary message"}}') is None


def test_observation_expires_without_refresh_or_replay():
    value=request();value.update(since=1,until=1000)
    with pytest.raises(PermissionError):challenge(value)


def test_candidate_commit_is_idempotent_metadata_only_and_never_admits_native_input(tmp_path):
    inbox=NativeInbox(tmp_path/'native.db',Redactor());store=Candidates(inbox)
    item={'sender':'$:LWCP_v1:$opaque-owner','chat':'cidExactConversation/+=','scope':'dingtalk:'+'a'*64,
        'thread':'','message_id':'observed-message','conversation_type':'1','created_at':123,
        'source_sha256':'b'*64,'challenge_sha256':'c'*64,'authorized':False,'mission_created':False,'message_sent':False}
    try:
        receipt=store.retain('dingtalk',item);assert receipt==store.retain('dingtalk',deepcopy(item))
        assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==0
        saved=inbox.db.execute('SELECT metadata FROM dingtalk_pairing_candidates').fetchone()[0]
        assert json.loads(saved)==item and 'client_secret' not in saved and 'sessionWebhook' not in saved
        with pytest.raises(Conflict):store.retain('dingtalk',{**item,'sender':'another-opaque-sender'})
        assert inbox.db.execute('SELECT COUNT(*) FROM dingtalk_pairing_candidates').fetchone()[0]==1
        for change in [{'authorized':True},{'mission_created':True},{'message_sent':True},{'extra':'private'},{'sender':'https://invalid'}]:
            with pytest.raises(ValueError):store.retain('dingtalk',{**item,**change})
    finally:inbox.close()
