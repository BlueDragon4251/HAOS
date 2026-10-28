import hashlib
import json
import time
import pytest

from haos.gateway_email_process import message_response


def packet(**changes):
    content=b'From: owner@example.invalid\r\nMessage-ID: <goal@example.invalid>\r\n\r\nA complete goal body.'
    end=content.index(b'\r\n\r\n')+4;head=hashlib.sha256(content[:end]).hexdigest();stamp=time.time()-1
    route={'binding_id':'owner','binding_digest':'b'*64}
    metadata={'uid':9,'uid_validity':77,'uid_next':10,'internal_at':stamp,'size':len(content),
        'sha256':hashlib.sha256(content).hexdigest(),'approval':{'binding_id':'owner','binding_digest':'b'*64,
            'received_at':stamp,'header_sha256':head,'envelope':{},'rfc_message_id':'<goal@example.invalid>'}}
    metadata.update(changes)
    return json.dumps(metadata).encode()+b'\n'+content,head,route


def test_binary_mail_frame_keeps_exact_content_with_bounded_source_approval():
    raw,head,route=packet();result=message_response(raw,9,77,head,route)
    assert result['content'].endswith(b'A complete goal body.') and result['size']==len(result['content'])


@pytest.mark.parametrize('change',[{'uid':10},{'uid':True},{'uid_validity':88},{'uid_next':9},
    {'internal_at':float('nan')},{'size':1},{'size':True},{'sha256':'0'*64},{'unexpected':'data'}])
def test_body_frame_rejects_wrong_resource_epoch_nonfinite_time_or_content(change):
    raw,head,route=packet(**change)
    with pytest.raises(ValueError):message_response(raw,9,77,head,route)


@pytest.mark.parametrize('change',['partial','trailing','header','route'])
def test_partial_or_rebound_body_never_becomes_an_admitted_message(change):
    raw,head,route=packet()
    if change=='partial':raw=raw[:-1]
    elif change=='trailing':raw+=b'extra data'
    elif change=='header':head='f'*64
    else:route={**route,'binding_digest':'c'*64}
    with pytest.raises((ValueError,PermissionError)):message_response(raw,9,77,head,route)
