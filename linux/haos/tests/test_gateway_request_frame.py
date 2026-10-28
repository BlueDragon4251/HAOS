import asyncio
import pytest

from haos import gateway_runtime


@pytest.mark.parametrize('params',[{'text':'x'*131072},{'offset':float('nan')},{'offset':float('inf')}])
def test_invalid_request_is_refused_before_connecting_to_a_controller(tmp_path,monkeypatch,params):
    # Configure a nonexistent private fixture address, never an installed socket.
    address=tmp_path/'not-created.sock';monkeypatch.setattr(gateway_runtime,'SOCKET',str(address))
    with pytest.raises(ValueError):asyncio.run(gateway_runtime.call('gateway.media.begin',params))
    assert not address.exists()
