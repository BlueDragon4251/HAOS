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
from .store import Conflict

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


def native_authorization_prefilter(policy, connector, user_id, chat_id, *, thread_id=None, is_bot=False):
    """Early Telegram gate; full scoped authorization still occurs on ingress.

    The pinned callback has no workspace field. Never turn that incomplete
    context into an authorization for another platform's credentialed actions.
    """
    row = policy.connectors.get(connector)
    if not row or row["platform"] != "telegram" or is_bot is not False or not user_id or not chat_id:
        return False
    return any(binding["connector"] == connector and binding["sender"] == str(user_id)
        and binding["chat"] == str(chat_id) and binding["thread"] == str(thread_id or "")
        and binding["scope"] == "" for binding in policy.bindings.values())


def build_adapter(platform: str, credentials: dict):
    if (platform not in SUPPORTED or not isinstance(credentials, dict)
            or set(credentials) - ({"token", "extra", "app_token"} if platform=='slack' else {"token", "extra"})
            or not isinstance(credentials.get("extra", {}), dict)):
        raise ValueError("unsupported adapter configuration")
    # Use the native hardening switch before importing any bundled adapter.
    os.environ["HERMES_SAFE_MODE"] = "1"
    from gateway.config import PlatformConfig
    from gateway.platform_registry import PlatformEntry
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
    if platform == "discord":
        # Native auto-threading, role/slash policy and unrelated channel context
        # cannot widen the exact HAOS-owned route or become agent instructions.
        extra.update(auto_thread=False, free_response_auto_thread=False, history_backfill=False, slash_commands=False)
    if platform == 'slack':
        from .gateway_slack import validate_credentials
        validate_credentials(credentials.get('token'),credentials.get('app_token'))
        extra.update(reply_in_thread=False,dm_top_level_threads_as_sessions=False,reactions=False)
    config = PlatformConfig(enabled=True, token=credentials.get("token"), extra=extra)
    if entry.validate_config and not entry.validate_config(config):
        raise ValueError("adapter configuration rejected")
    # Avoid the registry's optional runtime installer: immutable images must never pip-install.
    from .gateway_ingress import durable_adapter
    if platform == 'slack':
        import uuid
        from .gateway_slack import secret_scope
        home='/var/lib/haos-gateway/private-scope/'+uuid.uuid4().hex
        secrets={'SLACK_APP_TOKEN':credentials['app_token'],'SLACK_BOT_TOKEN':credentials['token']}
        with secret_scope(secrets,home):
            adapter=durable_adapter(entry.adapter_factory(config))
        adapter._haos_secrets=secrets;adapter._haos_secret_home=home
        return adapter
    return durable_adapter(entry.adapter_factory(config))


class SafeFormatter(logging.Formatter):
    def __init__(self, redactor):
        super().__init__("%(levelname)s %(name)s %(message)s")
        self.redactor = redactor

    def format(self, record):
        return self.redactor.text(super().format(record))


async def serve():
    from .gateway_publication import pending, validate_snapshot
    config = Path("/etc/haos")
    if pending(config):
        raise PermissionError("gateway owner publication requires recovery")
    snapshot = trusted_json(config / "gateways.json")
    policy = GatewayPolicy(snapshot)
    credentials = json.loads((Path(os.environ["CREDENTIALS_DIRECTORY"]) / "gateway-credentials").read_text())
    validate_snapshot(snapshot, credentials)
    if pending(config):
        raise PermissionError("gateway owner publication changed during startup")
    redactor = Redactor([item[key] for item in credentials["connectors"].values()
        for key in ('token','app_token') if item.get(key)])
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter(redactor))
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    inbox = RelayInbox(Path("/var/lib/haos-gateway/inbox.db"), redactor)
    native_inbox = None
    if any(row["platform"] in {'discord','slack'} for row in policy.connectors.values()):
        from .gateway_raw import NativeInbox
        native_inbox = NativeInbox(Path("/var/lib/haos-gateway/native-inbox.db"), redactor)
    stop = asyncio.Event()
    def current_policy():
        current = GatewayPolicy(trusted_json(config / "gateways.json"))
        if pending(config) or current.publication != policy.publication:
            stop.set()
            raise PermissionError("gateway owner publication changed; restart required")
        return current
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    # Adapter instances must be shared with the delivery loop; one transport owns both directions.
    tasks = []
    adapters = {}
    for connector in policy.connectors.values():
        adapter = build_adapter(connector["platform"], credentials["connectors"][connector["id"]])
        adapters[connector["id"]] = adapter
        def receive(event, connector=connector):
            try:
                envelope = adapter_envelope(event, connector["platform"])
                current = current_policy()
                # Commit before returning from native dispatch; transport-level
                # acknowledgement ordering also needs platform-specific SDK proof.
                inbox.admit(current, connector["id"], envelope)
                return True
            except (PermissionError, ValueError):
                logging.warning("Gateway message refused")
            return False
        adapter.set_durable_message_handler(receive)
        def authorize(user_id, chat_type=None, chat_id=None, *, is_bot=False, thread_id=None, connector=connector):
            try:
                current = current_policy()
                return native_authorization_prefilter(current, connector["id"], user_id, chat_id,
                    thread_id=thread_id, is_bot=is_bot)
            except Exception:
                logging.warning("Gateway authorization policy unavailable")
                return False
        adapter.set_authorization_check(authorize)
        if connector['platform'] in {'discord','slack'}:
            from types import SimpleNamespace
            adapter._haos_native = SimpleNamespace(inbox=native_inbox,connector=connector['id'],policy=current_policy)
        if connector["platform"] == "discord":
            from . import gateway_discord
            def capture(client, payload, connector=connector, adapter=adapter):
                try:
                    current = current_policy()
                except PermissionError:
                    return False
                envelope = gateway_discord.capture_envelope(adapter, client, payload, current, connector["id"])
                if envelope is None:
                    return False
                native_inbox.admit(current, connector["id"], envelope, payload)
                return True
            adapter._haos_native_capture = capture
            def authorize_source(envelope, connector=connector):
                try:
                    current_policy().authorize(connector["id"], envelope)
                    return True
                except (PermissionError, ValueError):
                    return False
            adapter._haos_source_authorizer = authorize_source
        tasks.append(asyncio.create_task(maintain(adapter, stop)))
        if connector['platform'] == 'discord':
            from .gateway_discord_history import maintain as recover_discord_history
            tasks.append(asyncio.create_task(recover_discord_history(adapter,stop,current_policy,connector['id'])))
    try:
        while not stop.is_set():
            for task in tasks:
                if task.done():
                    await task
                    raise ConnectionError("gateway maintenance task stopped")
            try:
                current = current_policy()
                if native_inbox is not None:
                    for connector_id, adapter in adapters.items():
                        platform=policy.connectors[connector_id]['platform']
                        if platform in {'discord','slack'} and adapter.is_connected:
                            key = native_inbox.due(connector_id)
                            if key is not None:
                                try:
                                    if platform=='slack':
                                        from . import gateway_slack
                                        dispatch=gateway_slack.dispatch_stored
                                    else:dispatch=gateway_discord.dispatch_stored
                                    await asyncio.wait_for(dispatch(adapter,adapter._haos_native_dispatch,key),15)
                                except (OSError, ValueError, Conflict, TimeoutError):
                                    logging.warning("Native gateway input deferred for recovery")
                incoming = inbox.next(current)
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
                    current_policy()
                    adapter = adapters[delivery["connector"]]
                    if not adapter.is_connected:
                        result = {"status": "retry", "retry_after": 5}
                    else:
                        metadata = {"notify": True, "haos_scope": delivery["scope"]}
                        if delivery["thread"]:
                            metadata["thread_id"] = delivery["thread"]
                        if delivery["scope"] and policy.connectors[delivery["connector"]]["platform"] == "slack":
                            metadata["slack_team_id"] = delivery["scope"]
                        try:
                            receipt = await asyncio.wait_for(adapter.send(delivery["chat"], delivery["content"], reply_to=delivery["reply_to"], metadata=metadata), 60)
                            from .gateway_delivery import delivery_result
                            result = delivery_result(receipt, redactor)
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
        for adapter in adapters.values():adapter._haos_stopping=True
        await asyncio.gather(*tasks, return_exceptions=True)
        receivers = {task for adapter in adapters.values() for task in getattr(adapter, '_haos_receive_tasks', set())}
        for task in receivers:
            task.cancel()
        await asyncio.gather(*receivers, return_exceptions=True)
        inbox.close()
        if native_inbox is not None:
            native_inbox.close()


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
