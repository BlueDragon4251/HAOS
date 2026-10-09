"""Connect official Hermes adapters to the peer-authenticated mission ingress."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import signal
from pathlib import Path

from .gateway import GatewayPolicy, SUPPORTED
from .gateway_relay import RelayInbox
from .redaction import Redactor
from .sandbox import trusted_json

SOCKET = "/run/haos-gateway-control/gateway.sock"


async def call(method: str, params: dict):
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(SOCKET, limit=131072), 10)
    try:
        writer.write(json.dumps({"method": method, "params": params}).encode() + b"\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), 15)
        if len(line) > 131072 or not line.endswith(b"\n"):
            raise ConnectionError("invalid controller response")
        reply = json.loads(line)
        if reply.get("ok") is not True:
            raise PermissionError("controller rejected gateway request")
        return reply["result"]
    finally:
        writer.close()
        await writer.wait_closed()


def adapter_envelope(event, platform: str):
    source = event.source
    if source is None or getattr(source.platform, "value", None) != platform or event.internal:
        raise PermissionError("invalid native adapter source")
    # Never admit paths from adapter metadata as files in the agent's namespace.
    if event.media_urls or getattr(event.message_type, "value", None) not in {"text", "command"}:
        raise ValueError("attachment and voice admission require a configured media broker")
    if not event.message_id or not source.user_id:
        raise PermissionError("stable sender and message identity required")
    return {"platform": platform, "sender": str(source.user_id), "chat": str(source.chat_id),
            "scope": str(source.scope_id or ""), "thread": str(source.thread_id or ""),
            "message_id": str(event.message_id), "is_bot": source.is_bot, "text": event.text}


def build_adapter(platform: str, credentials: dict):
    from gateway.config import PlatformConfig
    from gateway.platform_registry import PlatformEntry
    if platform not in SUPPORTED or set(credentials) - {"token", "extra"}:
        raise ValueError("unsupported adapter configuration")
    # These are immutable bundled upstream modules; no user/plugin directory is discovered.
    module = importlib.import_module(f"plugins.platforms.{platform}.adapter")
    entries = {}
    class Context:
        def register_platform(self, **kwargs):
            entry = PlatformEntry(**kwargs)
            entries[entry.name] = entry
    module.register(Context())
    entry = entries.get(platform)
    if entry is None or not entry.check_fn():
        raise RuntimeError("pinned messaging dependencies unavailable")
    extra = dict(credentials.get("extra", {}))
    if platform == "telegram":
        # Reboot/reconnect must not discard messages waiting at the authentic transport.
        extra["drop_pending_on_cold_boot"] = False
    config = PlatformConfig(enabled=True, token=credentials.get("token"), extra=extra)
    if entry.validate_config and not entry.validate_config(config):
        raise ValueError("adapter configuration rejected")
    # Avoid the registry's optional runtime installer: immutable images must never pip-install.
    return entry.adapter_factory(config)


class SafeFormatter(logging.Formatter):
    def __init__(self, redactor):
        super().__init__("%(levelname)s %(name)s %(message)s")
        self.redactor = redactor

    def format(self, record):
        return self.redactor.text(super().format(record))


async def serve():
    policy = GatewayPolicy(trusted_json(Path("/etc/haos/gateways.json")))
    credentials = json.loads((Path(os.environ["CREDENTIALS_DIRECTORY"]) / "gateway-credentials").read_text())
    if set(credentials) != {"connectors"} or set(credentials["connectors"]) != set(policy.connectors):
        raise ValueError("gateway credentials and owner policy disagree")
    redactor = Redactor([item["token"] for item in credentials["connectors"].values() if item.get("token")])
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter(redactor))
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    inbox = RelayInbox(Path("/var/lib/haos-gateway/inbox.db"), redactor)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    # Adapter instances must be shared with the delivery loop; one transport owns both directions.
    tasks = []
    adapters = {}
    for connector in policy.connectors.values():
        adapter = build_adapter(connector["platform"], credentials["connectors"][connector["id"]])
        adapters[connector["id"]] = adapter
        async def receive(event, connector=connector):
            try:
                envelope = adapter_envelope(event, connector["platform"])
                current_policy = GatewayPolicy(trusted_json(Path("/etc/haos/gateways.json")))
                # Commit synchronously before returning control to the transport's acknowledgement.
                inbox.admit(current_policy, connector["id"], envelope)
            except (PermissionError, ValueError):
                logging.warning("Gateway message refused")
            return None
        adapter.set_message_handler(receive)
        tasks.append(asyncio.create_task(maintain(adapter, stop)))
    try:
        while not stop.is_set():
            for task in tasks:
                if task.done():
                    await task
                    raise ConnectionError("gateway maintenance task stopped")
            try:
                current_policy = GatewayPolicy(trusted_json(Path("/etc/haos/gateways.json")))
                incoming = inbox.next(current_policy)
                if incoming:
                    try:
                        response = await call("gateway.receive", {"connector": incoming["connector"], "envelope": incoming["envelope"]})
                        inbox.admitted(incoming["id"], response["mission_id"])
                    except PermissionError:
                        inbox.denied(incoming["id"])
                    except (OSError, ConnectionError, TimeoutError):
                        # Ingress is idempotent even if the previous response was lost.
                        inbox.retry(incoming["id"])
                delivery = await call("gateway.next", {})
                if delivery:
                    adapter = adapters[delivery["connector"]]
                    if not adapter.is_connected:
                        result = {"status": "retry", "retry_after": 5}
                    else:
                        metadata = {"thread_id": delivery["thread"]} if delivery["thread"] else {}
                        if delivery["scope"] and policy.connectors[delivery["connector"]]["platform"] == "slack":
                            metadata["slack_team_id"] = delivery["scope"]
                        try:
                            receipt = await asyncio.wait_for(adapter.send(delivery["chat"], delivery["content"], reply_to=delivery["reply_to"], metadata=metadata), 60)
                            if receipt.success and receipt.message_id:
                                result = {"status": "delivered", "message_id": str(receipt.message_id)}
                            elif receipt.retryable or receipt.error_kind == "rate_limited":
                                result = {"status": "retry", "retry_after": min(86400, max(1, receipt.retry_after or 5))}
                            else:
                                result = {"status": "failed"}
                        except Exception:
                            result = {"status": "uncertain"}
                    await call("gateway.ack", {"id": delivery["id"], "result": {**result, "attempt": delivery["attempt"]}})
            except (OSError, ConnectionError, PermissionError, TimeoutError):
                logging.warning("Gateway controller unavailable or pairing revoked")
            try:
                await asyncio.wait_for(stop.wait(), 1)
            except TimeoutError:
                pass
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        inbox.close()


async def maintain(adapter, stop):
    delay = 1
    while not stop.is_set():
        try:
            if not await asyncio.wait_for(adapter.connect(), 60):
                raise ConnectionError("adapter connection refused")
            delay = 1
            while not stop.is_set() and adapter.is_connected:
                try:
                    await asyncio.wait_for(stop.wait(), 1)
                except TimeoutError:
                    pass
        except Exception as error:
            logging.warning("Gateway reconnect: %s", type(error).__name__)
        finally:
            try:
                await asyncio.wait_for(adapter.disconnect(), 15)
            except Exception:
                logging.warning("Gateway disconnect did not complete")
        try:
            await asyncio.wait_for(stop.wait(), delay)
        except TimeoutError:
            pass
        delay = min(60, delay * 2)


if __name__ == "__main__":
    asyncio.run(serve())
