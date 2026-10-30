from datetime import datetime,timezone
import pytest

from haos.gateway_email_imap import fetched,internal_date


def packet(uid=9,stamp='28-Oct-2026 13:00:00 +0200',size=1000):
    raw=b'Date: Fri, 1 Jan 1999 00:00:00 +0000\r\nFrom: owner@example.invalid\r\n\r\n'
    head=f'1 (UID {uid} INTERNALDATE "{stamp}" RFC822.SIZE {size} BODY[HEADER] {{{len(raw)}}}'.encode()
    return [(head,raw),b')']


def test_mail_server_internaldate_not_the_sender_date_establishes_received_time():
    value=fetched(packet(),9)
    assert value['internal_at']==datetime(2026,10,28,11,tzinfo=timezone.utc).timestamp()
    assert value['uid']==9 and value['size']==1000 and b'1999' in value['content']


@pytest.mark.parametrize('date',['31-Feb-2026 00:00:00 +0000','28-Oct-2026 00:00:00 +0060',
    '28-Oct-2026 00:00:00 +2400','28-Oct-2026 00:00:61 +0000','28-XXX-2026 00:00:00 +0000','yesterday'])
def test_invalid_server_received_times_are_refused(date):
    with pytest.raises(ValueError):internal_date(date)


@pytest.mark.parametrize('kind',['uid','duplicate-uid','duplicate-size','size','literal','partial','extra','closing','section'])
def test_changed_or_incomplete_mailbox_resource_cannot_be_admitted(kind):
    value=packet();head,raw=value[0]
    if kind=='uid':head=head.replace(b'UID 9',b'UID 10')
    elif kind=='duplicate-uid':head=head.replace(b'UID 9',b'UID 9 UID 9')
    elif kind=='duplicate-size':head=head.replace(b'RFC822.SIZE 1000',b'RFC822.SIZE 1000 RFC822.SIZE 1000')
    elif kind=='size':head=head.replace(b'RFC822.SIZE 1000',b'RFC822.SIZE 1')
    elif kind=='literal':head=head.replace(str(len(raw)).encode()+b'}',b'1}')
    elif kind=='partial':raw=raw[:-1]
    elif kind=='section':head=head.replace(b'BODY[HEADER]',b'BODY[]')
    value[0]=(head,raw)
    if kind=='extra':value.append(value[0])
    elif kind=='closing':value[-1]=b'changed source'
    with pytest.raises(ValueError):fetched(value,9)


@pytest.mark.parametrize('change',[{'uid':10},{'uid_validity':88},{'uid_validity':True},{'uid_next':9},
    {'internal_at':float('nan')},{'internal_at':float('inf')},{'size':1},
    {'content_base64':'not base64'},{'sha256':'f'*64},{'unexpected':'field'}])
def test_private_header_pipe_rejects_changed_uid_epoch_size_bytes_and_nonfinite_time(change):
    import base64,hashlib,time
    from haos.gateway_email_process import header_response
    content=b'From: owner@example.invalid\r\n\r\n'
    value={'uid':9,'uid_validity':77,'uid_next':10,'internal_at':time.time()-1,'size':1000,
        'content_base64':base64.b64encode(content).decode(),'sha256':hashlib.sha256(content).hexdigest()}
    with pytest.raises(ValueError):header_response({**value,**change},9,77)


def test_private_header_pipe_returns_verified_original_bytes_or_finite_epoch_refusal():
    import base64,hashlib,time
    from haos.gateway_email_process import header_response
    content=b'From: owner@example.invalid\r\n\r\n'
    value={'uid':9,'uid_validity':77,'uid_next':10,'internal_at':time.time()-1,'size':1000,
        'content_base64':base64.b64encode(content).decode(),'sha256':hashlib.sha256(content).hexdigest()}
    assert header_response(value,9,77)['content']==content
    assert header_response({'error':'uid-state-changed'},9,77)=={'error':'uid-state-changed'}


@pytest.mark.parametrize('change',[{'uid_validity':88},{'uid_validity':True},{'uid_next':9},{'after':1},
    {'uids':[1,1]},{'uids':[3,1]},{'uids':[10]},{'uids':[True]},{'unexpected':'field'}])
def test_private_search_pipe_rejects_stale_epochs_ranges_and_incomplete_uid_sets(change):
    from haos.gateway_email_process import search_response
    page={'uid_validity':77,'after':0,'through':9}
    value={**page,'uid_next':10,'uids':[1,3,9]}
    with pytest.raises(ValueError):search_response({**value,**change},page)


def test_private_search_pipe_preserves_exact_complete_ordered_uid_resources():
    from haos.gateway_email_process import search_response
    page={'uid_validity':77,'after':0,'through':9};value={**page,'uid_next':10,'uids':[1,3,9]}
    assert search_response(value,page)==value
