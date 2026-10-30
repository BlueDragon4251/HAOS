"""Independent attachment boundaries; no native network or SDK replacement."""
import fcntl
import os

import pytest

from haos.gateway_buzz_upload import descriptor,sealed
from haos.gateway_buzz_send_process import body,media_tags,target

ACCOUNT={'relay_url':'https://buzz.fixture.invalid','channels':['01234567-89ab-4cde-8012-3456789abcde']}


def blob():return {'url':ACCOUNT['relay_url']+'/media/'+'a'*64+'.pdf','sha256':'a'*64,'size':42,
    'type':'application/pdf','uploaded':1793332800}


def reply():return {'channel':ACCOUNT['channels'][0],'anchor':'b'*64,'thread':'c'*64,'kind':9,'content':'Approved file',
    'allowed_mentions':[],'explicit_mentions':[],'attachments':[{'name':'result-0.pdf','descriptor':blob()}]}


@pytest.mark.parametrize('change',[{'url':'https://foreign.fixture.invalid/media/'+'a'*64+'.pdf'},
    {'url':ACCOUNT['relay_url']+'/media/'+'b'*64+'.pdf'},{'url':ACCOUNT['relay_url']+'/admin/export'},
    {'sha256':'B'*64},{'size':True},{'size':0},{'size':8388609},{'uploaded':True},
    {'type':'text/html\nAuthorization: private'},{'duration':float('inf')},{'duration':True},
    {'dim':'100000x200'},{'blurhash':'x\ny'},{'thumb':'https://foreign.fixture.invalid/thumb.png'},
    {'filename':'../../owner'},{'extra':'opaque'}])
def test_untrusted_upload_receipt_cannot_expand_network_size_protocol_or_metadata_authority(change):
    with pytest.raises((ValueError,PermissionError)):descriptor(ACCOUNT,{**blob(),**change})


@pytest.mark.parametrize('name',['../owner','-option\n--broadcast','a b.pdf','.hidden','ä.pdf','x'*121])
def test_descriptor_handoff_never_carries_agent_paths_flags_or_markup(name):
    item=reply();item['attachments'][0]['name']=name
    with pytest.raises(PermissionError):target(ACCOUNT,item)


def test_sealed_descriptor_keeps_exact_native_imeta_fields_and_rejects_additions_or_changed_order():
    item=reply();assert target(ACCOUNT,item)[:2]==['messages','send']
    assert body(ACCOUNT,item)=='Approved file\n[result-0.pdf]('+blob()['url']+')'
    tag=['imeta','url '+blob()['url'],'m application/pdf','x '+'a'*64,'size 42','filename result-0.pdf']
    assert media_tags(ACCOUNT,item,[tag])
    assert not media_tags(ACCOUNT,item,[tag+['url https://foreign.fixture.invalid/file']])
    assert not media_tags(ACCOUNT,item,[tag,tag])
    assert not media_tags(ACCOUNT,item,[tag[:3]+['x '+'b'*64]+tag[4:]])


def test_actual_linux_memory_descriptor_is_non_shrinkable_non_growable_non_writable_and_cannot_remove_seals():
    fd=sealed('haos-buzz-test',b'Exact root snapshot')
    try:
        assert os.read(fd,64)==b'Exact root snapshot'
        seals=fcntl.fcntl(fd,getattr(fcntl,'F_GET_SEALS',1034))
        assert seals==15
        with pytest.raises(PermissionError):os.write(fd,b'changed')
        with pytest.raises(PermissionError):os.ftruncate(fd,1)
        with pytest.raises(PermissionError):fcntl.fcntl(fd,getattr(fcntl,'F_ADD_SEALS',1033),0)
    finally:os.close(fd)
