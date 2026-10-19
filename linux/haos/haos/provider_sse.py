"""Bounded SSE event framing, including multiline JSON data fields."""
import time


def require_complete(response):
    """Bounded HTTPResponse.read/readline do not reject a short fixed body.

    EOF alone is only sufficient for a close-delimited response. Chunked
    decoding has its own stdlib framing checks; known lengths must reach zero.
    """
    if getattr(response, "length", None) not in {None, 0}:
        raise ConnectionError("provider ended before completing its HTTP body")


def events(response, *, max_line, max_output, deadline):
    total, fields, data = 0, [], []
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("model stream exceeded broker deadline")
        raw = response.readline(max_line + 1)
        if not raw:
            if fields or data:
                raise ConnectionError("provider stream ended inside an event")
            require_complete(response)
            return
        total += len(raw)
        if len(raw) > max_line or total > max_output:
            raise ValueError("model stream exceeded broker bounds")
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if fields or data:
                yield fields, "\n".join(data) if data else None
            fields, data = [], []
        elif line.startswith("data:"):
            text = line[5:]
            data.append(text[1:] if text.startswith(" ") else text)
        else:
            fields.append(line)
