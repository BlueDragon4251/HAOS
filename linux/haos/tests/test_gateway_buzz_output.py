"""Real SQLite custody rejects removed bytes, stale accounts and unfinished uploads."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from haos.gateway import Conflict,digest
from haos.gateway_buzz import PreparedBuzzPolicy,scope
from haos.gateway_buzz_output import Output
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor


@pytest.fixture
def retained(tmp_path):
    value={'private_key':'1'*64,'public_key':'2'*64,'relay_url':'https://buzz.fixture.invalid',
        'channels':['01234567-89ab-4cde-8012-3456789abcde']}
    binding={'id':'owner','connector':'buzz','sender':'3'*64,'chat':value['channels'][0],'scope':scope(value),
        'thread':'','identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':1,'allow_outbound_media':True}
    config={'version':1,'connectors':[{'id':'buzz','platform':'buzz'}],'bindings':[binding]}
    policy=lambda:PreparedBuzzPolicy(config)
    native=NativeInbox(tmp_path/'native.db',Redactor([value['private_key']]))
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(inbox=native,policy=policy,connector='buzz'),
        _haos_buzz_value=value,_haos_buzz_check=lambda:None)
    output=Output(adapter);delivery={'id':'a'*64,'binding_id':'owner','binding_digest':digest(binding)}
    data=b'%PDF-1.7\nRetained fixture bytes';sha=hashlib.sha256(data).hexdigest()
    item={'url':value['relay_url']+'/media/'+sha+'.pdf','sha256':sha,'size':len(data),'type':'application/pdf','uploaded':1793332800}
    native.db.execute('INSERT INTO buzz_output_uploads VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
        ('b'*64,delivery['id'],'c'*64,digest(binding),digest(value),'result-0.pdf',sha,'ready',
            json.dumps(item,sort_keys=True,separators=(',',':')),data,data,1793332800))
    try:yield output,delivery,config,adapter
    finally:native.close()


def test_retained_exact_blob_is_reused_without_network_or_native_optional_import(retained):
    output,delivery,_,_=retained
    assert output.resolve(delivery,['b'*64])[0]['name']=='result-0.pdf'
    assert output.db.execute('SELECT COUNT(*) FROM buzz_output_uploads').fetchone()[0]==1


@pytest.mark.parametrize('change',[
    "UPDATE buzz_output_uploads SET source=x'00'",
    "UPDATE buzz_output_uploads SET stored=x'00'",
    "UPDATE buzz_output_uploads SET descriptor='{}'",
    "UPDATE buzz_output_uploads SET state='uploading'",
    "UPDATE buzz_output_uploads SET credential_scope='old-account'",
    'DELETE FROM buzz_output_uploads'])
def test_restart_never_refetches_reuploads_or_restores_corrupt_or_unresolved_custody(retained,change):
    output,delivery,_,_=retained;output.db.execute(change)
    with pytest.raises(Conflict):output.resolve(delivery,['b'*64])


def test_changed_owner_epoch_or_rotated_private_account_cannot_reuse_old_attachment(retained):
    output,delivery,config,adapter=retained
    adapter._haos_buzz_value={**adapter._haos_buzz_value,'private_key':'4'*64}
    with pytest.raises(Conflict):output.resolve(delivery,['b'*64])
    config['bindings'][0]['generation']='d'*64
    with pytest.raises(PermissionError):output.resolve(delivery,['b'*64])
