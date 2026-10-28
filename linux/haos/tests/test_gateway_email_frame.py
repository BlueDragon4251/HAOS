import hashlib
from io import BytesIO
import pytest

from haos.gateway_email_frame import read,validate
from haos.gateway_email_smtp import descriptors


def fixture():
    data=b'An exact private SMTP attachment.'
    meta={'id':'a'*64,'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'name':'result-0.txt'}
    return meta,data


def test_private_binary_snapshot_stream_retains_exact_bytes_without_json_or_paths():
    meta,data=fixture();assert validate([meta],[data])==[meta]
    assert read(BytesIO(data),[meta],lambda:None)==[data]
    assert read(BytesIO(b''),[],lambda:None)==[]


@pytest.mark.parametrize('change',['truncated','extra','hash','wrong_count','wrong_bytes'])
def test_partial_extra_or_changed_private_bytes_never_become_an_smtp_attachment(change):
    meta,data=fixture()
    if change in {'wrong_count','wrong_bytes'}:
        with pytest.raises(ValueError):validate([meta],[] if change=='wrong_count' else [b'changed'])
    else:
        stream=data[:-1] if change=='truncated' else data+b'extra' if change=='extra' else b'x'*len(data)
        with pytest.raises(ValueError):read(BytesIO(stream),[meta],lambda:None)


@pytest.mark.parametrize('change',[{'name':'/owner/private.txt'},{'name':'result-0.txt\r\nBcc: other@example.invalid'},
    {'name':'result-0.unknown'},{'size':True},{'size':8*1024*1024+1},{'id':'bad'},{'sha256':'bad'},{'path':'/owner/private.txt'}])
def test_smtp_metadata_is_exact_bounded_and_cannot_select_host_paths(change):
    meta,_data=fixture()
    with pytest.raises(ValueError):descriptors([{**meta,**change}])


def test_more_than_four_or_repeated_snapshot_ids_are_not_admitted():
    meta,_data=fixture()
    with pytest.raises(ValueError):descriptors([{**meta,'name':f'result-{n}.txt'} for n in range(5)])
    with pytest.raises(ValueError):descriptors([meta,{**meta,'name':'result-1.txt'}])


def test_authority_withdrawal_stops_a_private_binary_read_between_chunks():
    meta,_data=fixture();data=b'x'*100000;meta.update(size=len(data),sha256=hashlib.sha256(data).hexdigest())
    stream=BytesIO(data);calls=[]
    def current():
        calls.append(True)
        if len(calls)==3:raise PermissionError('fixture authority withdrawn')
    with pytest.raises(PermissionError):read(stream,[meta],current)
    assert 0<stream.tell()<len(data)
