"""Bind Copilot's bounded upstream opener to Hermes's safe credential redirects."""
from types import SimpleNamespace
import urllib.parse
import urllib.request


def bind_transport():
    from hermes_cli import copilot_auth
    from hermes_cli.urllib_security import open_credentialed_url
    # A module-local proxy leaves stdlib urllib and every other provider alone.
    # The existing upstream DNS deadline, exchange lock/cache and device-code
    # state machine remain intact; cross-origin redirects cannot retain keys.
    copilot_auth.urllib = SimpleNamespace(parse=urllib.parse, request=SimpleNamespace(
        Request=urllib.request.Request, urlopen=open_credentialed_url))
