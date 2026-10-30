"""No optional SDK is needed to reject a missing durable capture receipt."""
import asyncio
import pytest
from haos.gateway_feishu_ws_frames import Bridge


@pytest.mark.parametrize('receipt',[None,False,True,'not-a-durable-receipt',{'accepted':True}])
def test_sdk_bridge_never_acknowledges_a_volatile_or_ambiguous_capture(receipt):
    loop=asyncio.new_event_loop();seen=[]
    try:
        def capture(raw):seen.append(raw);return receipt
        bridge=Bridge(loop,capture,lambda:None)
        with pytest.raises(PermissionError):bridge._do_without_validation(b'bounded source bytes')
        assert seen==[b'bounded source bytes']
    finally:loop.close()


def test_sdk_bridge_returns_no_internal_receipt_to_remote_peer_after_explicit_commit():
    loop=asyncio.new_event_loop();seen=[]
    try:
        def capture(raw):seen.append(raw);return 'a'*64
        bridge=Bridge(loop,capture,lambda:None)
        assert bridge._do_without_validation(b'bounded source bytes') is None
        assert seen==[b'bounded source bytes']
    finally:loop.close()
