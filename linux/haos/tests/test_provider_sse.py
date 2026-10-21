"""Protocol framing and failure boundaries independent of vendor accounts."""
from io import BytesIO, BufferedReader
import time

import pytest

from haos.provider_sse import events
from haos.provider_messages import restore


@pytest.mark.parametrize("tail,complete", [(b"0\r\n\r\n", True), (b"", False), (b"3\r\nab", False)])
def test_actual_stdlib_chunked_readline_cannot_hide_missing_terminal_chunk(tail, complete):
    import http.client
    class Socket:
        def makefile(self, *_):
            return BufferedReader(BytesIO(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nC\r\ndata: done\n\n\r\n" + tail))
    response = http.client.HTTPResponse(Socket())
    response.begin()
    frames = events(response, max_line=1024, max_output=4096, deadline=time.monotonic() + 5)
    assert next(frames) == ([], "done")
    if complete:
        assert list(frames) == []
    else:
        with pytest.raises((ConnectionError, http.client.IncompleteRead)):
            list(frames)


def parse(body, **limits):
    return list(events(BytesIO(body), max_line=limits.get("line", 1024),
        max_output=limits.get("output", 4096), deadline=limits.get("deadline", time.monotonic() + 5)))


def test_multiline_native_json_crlf_comments_and_utf8():
    result = parse(': heartbeat\r\nevent: content_block_delta\r\ndata: {"text":\r\ndata: "Grüße"}\r\n\r\n'.encode())
    assert result == [([": heartbeat", "event: content_block_delta"], '{"text":\n"Grüße"}')]


@pytest.mark.parametrize("body,limits,error", [
    (b"data: {}\n", {}, ConnectionError),
    (b"event: unfinished", {}, ConnectionError),
    (b"data: {}\n\n", {"line": 4}, ValueError),
    (b"data: {}\n\n", {"output": 5}, ValueError),
    (b"data: {}\n\n", {"deadline": 0}, TimeoutError),
    (b"data: \xff\n\n", {}, UnicodeError),
])
def test_incomplete_malformed_and_over_budget_frames_never_complete(body, limits, error):
    with pytest.raises(error):
        parse(body, **limits)


def test_restore_only_request_owned_tool_blocks_and_preserve_signed_content():
    data = {"content": [{"type": "tool_use", "name": "mcp__fixture", "input": {"name": "mcp__fixture"}},
        {"type": "thinking", "thinking": "mcp__fixture", "signature": "signed fixture"},
        {"type": "tool_use", "name": "mcp__unrequested"}]}
    result = restore(data, {"mcp__fixture": "fixture"})
    assert result["content"][0]["name"] == "fixture"
    assert result["content"][0]["input"]["name"] == "mcp__fixture"
    assert result["content"][1] == data["content"][1]
    assert result["content"][2] == data["content"][2]
    assert data["content"][0]["name"] == "mcp__fixture"
