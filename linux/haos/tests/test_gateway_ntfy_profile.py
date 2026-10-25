"""Private ntfy policy/config must remain usable without optional Hermes imports."""
from pathlib import Path
import subprocess
import sys

import pytest

from haos.gateway_ntfy_profile import credentials


def test_private_gateway_modules_import_with_no_site_packages_or_upstream():
    source = Path(__file__).resolve().parents[1]
    script = ('import sys; sys.path.insert(0,'+repr(str(source))+'); '
              'import haos.gateway_ntfy_profile, haos.gateway_ntfy_delivery, haos.gateway_ntfy_transport; '
              'assert "gateway.config" not in sys.modules; assert "plugins" not in sys.modules')
    result = subprocess.run([sys.executable,'-I','-S','-c',script],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('change', [
    {'token':''}, {'token':'newline\ncredential'}, {'token':'nul\0credential'},
    {'topic':'*'}, {'topic':'../neighbor'}, {'topic':'one/two'},
    {'server_url':'http://unsafe.invalid'}, {'server_url':'https://user:pass@host.invalid'},
    {'server_url':'https://host.invalid/%2fescape'}, {'server_url':'https://host.invalid/path/../escape'},
    {'extra':{'auto_authorize':True}},
])
def test_private_ntfy_configuration_refuses_ambiguous_or_unapproved_inputs(change):
    value={'token':'local-only-credential','topic':'private-topic','server_url':'https://owner.invalid'}
    with pytest.raises(ValueError):
        credentials({**value,**change})
