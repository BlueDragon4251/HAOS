"""Real SQLite retained-resource integrity; transport/process proofs are separate."""
import asyncio
from types import SimpleNamespace
import pytest
from haos.gateway import digest,Conflict
from haos.gateway_feishu import PreparedFeishuPolicy
from haos.gateway_feishu_media import retained
from haos.gateway_media_relay import MediaCache
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_feishu import account,binding


def prepare(tmp_path):
    grant={**binding(),'allow_media':True}
    policy=PreparedFeishuPolicy({'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[grant]})
    value=account();inbox=NativeInbox(tmp_path/'native.db',Redactor([value['app_secret']]))
    envelope={'platform':'feishu','sender':grant['sender'],'chat':grant['chat'],'thread':'','scope':grant['scope'],
        'message_id':'om_'+'f'*32,'is_bot':False,'text':'Approved retained resource'}
    key=inbox.admit(policy,'feishu',envelope,{'raw_id':'a'*64});row=inbox.claim(key,policy)
    cache=MediaCache(inbox);item=cache.put(policy,'feishu',envelope,b'original file','document')
    resource={'key':'file_v3_0000000000000000','type':'file','name':'','permissions':['allow_media']}
    original={'id':'a'*64,'resources':[resource]}
    native=SimpleNamespace(inbox=inbox,connector='feishu',policy=lambda:policy)
    adapter=SimpleNamespace(_haos_native=native,_haos_feishu_value=value,_haos_feishu_check=lambda:None)
    inbox.db.execute('CREATE TABLE feishu_input_media(input_id TEXT,resource_index INTEGER,fingerprint TEXT,upload_id TEXT,mime TEXT)')
    source=digest([row['binding_digest'],row['fingerprint'],original['id'],resource]);mime='application/octet-stream'
    proof=digest([source,item['id'],mime])
    inbox.db.execute('INSERT INTO feishu_input_media VALUES(?,?,?,?,?)',(row['id'],0,proof,item['id'],mime))
    return inbox,adapter,row,original,item


def test_retained_copy_replays_without_runtime_or_network_and_preserves_original_bytes(tmp_path):
    inbox,adapter,row,original,item=prepare(tmp_path)
    try:
        result=asyncio.run(retained(adapter,row,original))
        assert result[0]['item']['data']==b'original file' and result[0]['item']['id']==item['id']
    finally:inbox.close()


@pytest.mark.parametrize('column,value',[('mime','audio/ogg'),('mime','not a MIME'),('upload_id','b'*64),('fingerprint','0'*64)])
def test_corrupted_resource_pointer_or_mime_is_refused_before_any_sdk_worker(tmp_path,column,value):
    inbox,adapter,row,original,item=prepare(tmp_path)
    try:
        inbox.db.execute('UPDATE feishu_input_media SET '+column+'=?',(value,))
        with pytest.raises(Conflict):asyncio.run(retained(adapter,row,original))
    finally:inbox.close()


@pytest.mark.parametrize('status,deadline',[('unknown',0),('rate-limited',-1),('ready','damaged'),('ready',None)])
def test_damaged_account_backoff_is_not_interpreted_as_permission_to_fetch(tmp_path,status,deadline):
    inbox,adapter,row,original,item=prepare(tmp_path)
    try:
        inbox.db.execute('DELETE FROM feishu_input_media')
        inbox.db.execute('CREATE TABLE feishu_delivery_backoff(account_scope TEXT PRIMARY KEY,status TEXT,next_attempt REAL,updated_at REAL)')
        value=adapter._haos_feishu_value
        account_id=digest([value[key] for key in ['domain','app_id','app_secret','tenant_key','bot_open_id']])
        inbox.db.execute('INSERT INTO feishu_delivery_backoff VALUES(?,?,?,0)',(account_id,status,deadline))
        with pytest.raises(Conflict):asyncio.run(retained(adapter,row,original))
    finally:inbox.close()
