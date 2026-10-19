"""Bounded aggregate usage read; no key refresh, model dispatch or private history."""

import http.client
import json
import math
import re

from .provider_policy import PORT

COUNTERS = ("requests_day", "requests_minute", "requests_per_day", "requests_per_minute",
            "finished_requests_day", "unfinished_requests_day", "http_success_day", "http_error_day", "usage_reported_requests_day")
TOKEN_COUNTS = ("input_tokens_reported_day", "output_tokens_reported_day")


def validate_snapshot(value):
    expected = {*COUNTERS, *TOKEN_COUNTS, "snapshot_at", "scope", "window_seconds", "cost_available", "monetary_cost"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("unexpected aggregate usage fields")
    if (type(value["snapshot_at"]) not in {int, float} or not math.isfinite(value["snapshot_at"]) or value["snapshot_at"] < 0
            or value["scope"] != "broker" or type(value["window_seconds"]) is not int or value["window_seconds"] != 86400
            or value["cost_available"] is not False or value["monetary_cost"] is not None):
        raise ValueError("unverified usage scope or monetary claim")
    if any(type(value[k]) is not int or not 0 <= value[k] < 2**53 for k in COUNTERS):
        raise ValueError("invalid aggregate usage count")
    if any(value[k] is not None and (type(value[k]) is not int or not 0 <= value[k] < 2**53) for k in TOKEN_COUNTS):
        raise ValueError("invalid reported token count")
    if (not 1 <= value["requests_per_day"] <= 10000 or not 1 <= value["requests_per_minute"] <= 120
            or value["requests_minute"] > value["requests_day"]
            or value["finished_requests_day"] + value["unfinished_requests_day"] != value["requests_day"]
            or value["http_success_day"] + value["http_error_day"] > value["finished_requests_day"]
            or value["usage_reported_requests_day"] > value["finished_requests_day"]):
        raise ValueError("inconsistent aggregate usage receipt")
    return value


class UsageSampler:
    def __init__(self, capability):
        if not isinstance(capability, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", capability):
            raise ValueError("invalid scoped usage capability")
        self.capability = capability

    def sample(self):
        connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=2)
        try:
            connection.request("GET", "/v1/haos/usage", headers={"Authorization": "Bearer " + self.capability})
            response = connection.getresponse()
            if (response.status != 200 or response.getheader("Content-Type") != "application/json"
                    or response.getheader("Content-Encoding", "identity") != "identity"):
                raise ValueError("usage broker did not provide a fixed JSON receipt")
            body = response.read(65537)
            if len(body) > 65536:
                raise ValueError("aggregate usage exceeds its bound")
            return validate_snapshot(json.loads(body))
        finally:
            connection.close()
