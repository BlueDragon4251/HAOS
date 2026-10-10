#!/usr/bin/env python3
"""Verify the real bundled adapters' construction and API without a provider or network send."""

import inspect
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    sys.path.insert(0, sys.argv[1])
    from haos.gateway_runtime import adapter_envelope, build_adapter
    from gateway.config import Platform
    from gateway.platforms.event import MessageEvent, MessageType
    from gateway.session import SessionSource
    receipts = {}
    with tempfile.TemporaryDirectory(prefix="haos-gateway-contract-") as directory:
        os.environ["HERMES_HOME"] = str(Path(directory) / ".hermes")
        os.environ["HOME"] = directory
        for name in ("telegram", "discord"):
            adapter = build_adapter(name, {"token": "123456:" + "x" * 35})
            source = SessionSource(platform=Platform(name), chat_id="42", user_id="42")
            event = MessageEvent(text="Contract validation only", message_type=MessageType.TEXT, source=source, message_id="11")
            envelope = adapter_envelope(event, name)
            assert envelope["sender"] == "42" and envelope["message_id"] == "11"
            assert callable(adapter.set_message_handler) and inspect.iscoroutinefunction(adapter.connect)
            assert {"chat_id", "content", "reply_to", "metadata"} <= set(inspect.signature(adapter.send).parameters)
            assert adapter.is_connected is False
            if name == "telegram":
                assert adapter._drop_pending_on_cold_boot is False
            receipts[name] = {"native_adapter_constructed": True, "native_event_contract": True,
                              "connected": False, "external_delivery_tested": False}
    Path(sys.argv[2]).write_text(json.dumps(receipts, indent=2) + "\n")
    print(json.dumps(receipts))


if __name__ == "__main__":
    main()
