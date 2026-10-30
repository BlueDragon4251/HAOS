import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("runtime_prepare", Path(__file__).parents[1] / "runtime/prepare.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


@pytest.fixture
def inputs(tmp_path):
    upstream, overlay = tmp_path / "upstream", tmp_path / "overlay"
    upstream.mkdir()
    overlay.mkdir()
    (upstream / ".herald-os-upstream-sha").write_text("a" * 40 + "\n")
    (upstream / "pyproject.toml").write_text('dependencies = ["PyJWT[crypto]==2.13.0"]\n')
    (upstream / "uv.lock").write_text("fixture upstream lock\n")
    (upstream / "agent").mkdir()
    (upstream / "agent/auxiliary_client.py").write_text('''class CodexAuxiliaryClient: pass
def dispatch(task, provider, client, kwargs, stream=False):
    # Streaming path (MoA aggregator): return the raw SDK stream, skipping validation and
    if True:
        if task == "moa_aggregator" and isinstance(client, CodexAuxiliaryClient):
            return "buffered"
    return "standard"
''')
    (upstream/'plugins/platforms/a2a').mkdir(parents=True)
    (upstream/'plugins/platforms/a2a/adapter.py').write_text('''import urllib.request
class A2AAdapter:
    def _send_push_notification(self, task_id: str, context_id: str, reply: str, state: str) -> None:
        req=urllib.request.Request('https://fixture.invalid/callback',data=b'{}',method='POST')
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                return resp.status
        except OSError:
            return None
''')
    (upstream/'plugins/platforms/buzz').mkdir(parents=True)
    (upstream/'plugins/platforms/buzz/adapter.py').write_text('''class BuzzAdapter:
    async def _websocket_loop(self) -> None:
        import websockets
        while True:
            try:
                async with websockets.connect(
                    self._websocket_url(), open_timeout=_WS_AUTH_TIMEOUT, close_timeout=5,
                    ping_interval=20, ping_timeout=20, max_size=_WS_MAX_MESSAGE_BYTES,
                    happy_eyeballs_delay=0.25,
                ) as websocket:
                    return websocket
            except OSError:
                raise
''')
    (overlay / "requirements.txt").write_text("pyjwt==2.15.1 \\\n    --hash=sha256:" + "b" * 64 + "\n")
    source = {"upstream_commit": "a" * 40, "python": "3.11", "extras": ["web", "messaging", "anthropic", "bedrock", "vertex", "azure-identity", "matrix", "voice", "feishu", "dingtalk"],
              "security_versions": {"pyjwt": "2.15.1"}}
    for filename, key, root in [("pyproject.toml", "pyproject_sha256", upstream),
                                ("uv.lock", "uv_lock_sha256", upstream),
                                ("agent/auxiliary_client.py", "auxiliary_client_sha256", upstream),
                                ('plugins/platforms/a2a/adapter.py','a2a_adapter_sha256',upstream),
                                ('plugins/platforms/buzz/adapter.py','buzz_adapter_sha256',upstream),
                                ("requirements.txt", "requirements_sha256", overlay)]:
        source[key] = hashlib.sha256((root / filename).read_bytes()).hexdigest()
    (overlay / "source.json").write_text(json.dumps(source))
    return upstream, overlay


def test_check_does_not_mutate_upstream(inputs):
    before = (inputs[0] / "agent/auxiliary_client.py").read_bytes()
    transport=(inputs[0]/'plugins/platforms/a2a/adapter.py').read_bytes()
    buzz=(inputs[0]/'plugins/platforms/buzz/adapter.py').read_bytes()
    runtime.prepare(*inputs, check_only=True)
    assert "2.13.0" in (inputs[0] / "pyproject.toml").read_text()
    assert (inputs[0] / "agent/auxiliary_client.py").read_bytes() == before
    assert (inputs[0]/'plugins/platforms/a2a/adapter.py').read_bytes()==transport
    assert (inputs[0]/'plugins/platforms/buzz/adapter.py').read_bytes()==buzz


def test_reviewed_constraint_is_applied(inputs):
    runtime.prepare(*inputs)
    namespace = {}
    exec(compile((inputs[0] / "agent/auxiliary_client.py").read_bytes(), "fixture", "exec"), namespace)
    assert namespace["dispatch"]("moa_aggregator", "custom:other", namespace["CodexAuxiliaryClient"](), {}) == "buffered"
    assert '"PyJWT[crypto]==2.15.1"' in (inputs[0] / "pyproject.toml").read_text()


@pytest.mark.parametrize("file,root", [(".herald-os-upstream-sha", 0), ("pyproject.toml", 0),
                                     ("uv.lock", 0), ("requirements.txt", 1), ("agent/auxiliary_client.py", 0),('plugins/platforms/a2a/adapter.py',0),('plugins/platforms/buzz/adapter.py',0)])
def test_changed_inputs_are_refused_before_modification(inputs, file, root):
    path = inputs[root] / file
    path.write_text(path.read_text() + "tampered")
    before = (inputs[0] / "pyproject.toml").read_bytes()
    auxiliary = (inputs[0] / "agent/auxiliary_client.py").read_bytes()
    with pytest.raises(ValueError):
        runtime.prepare(*inputs)
    assert (inputs[0] / "pyproject.toml").read_bytes() == before
    assert (inputs[0] / "agent/auxiliary_client.py").read_bytes() == auxiliary


def test_mismatched_reviewed_security_version(inputs):
    path = inputs[1] / "source.json"
    source = json.loads(path.read_text())
    source["security_versions"]["pyjwt"] = "2.13.0"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="security version mismatch"):
        runtime.prepare(*inputs)


@pytest.mark.parametrize('change',['remove-matrix','remove-feishu','remove-dingtalk','add-all'])
def test_unreviewed_extra_set_is_refused_before_runtime_overlay_writes(inputs,change):
    path=inputs[1]/'source.json';source=json.loads(path.read_text())
    if change=='remove-matrix':source['extras'].remove('matrix')
    elif change=='remove-feishu':source['extras'].remove('feishu')
    elif change=='remove-dingtalk':source['extras'].remove('dingtalk')
    else:source['extras'].append('all')
    path.write_text(json.dumps(source))
    before=(inputs[0]/'agent/auxiliary_client.py').read_bytes()
    with pytest.raises(ValueError,match='runtime target changed'):runtime.prepare(*inputs)
    assert (inputs[0]/'agent/auxiliary_client.py').read_bytes()==before


def test_native_callback_transport_uses_scoped_opener_without_replacing_native_handler(inputs):
    from contextlib import contextmanager
    runtime.prepare(*inputs);namespace={};calls=[]
    exec(compile((inputs[0]/'plugins/platforms/a2a/adapter.py').read_bytes(),'fixture','exec'),namespace)
    @contextmanager
    def private_opener(request,*,timeout):
        calls.append((request.full_url,request.data,timeout))
        yield type('Response',(),{'status':204})()
    adapter=namespace['A2AAdapter']();adapter._open_push_notification=private_opener
    assert adapter._send_push_notification('task-fixture','context-fixture','reviewed result','completed')==204
    assert calls==[('https://fixture.invalid/callback',b'{}',10)]
