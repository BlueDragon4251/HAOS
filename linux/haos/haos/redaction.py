"""Remove credentials before mission data crosses a persistence or observer boundary."""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"
_SENSITIVE = re.compile(
    r"(?:password|passwd|secret|(?:^|[_-])token(?:$|[_-])|api[_-]?key|authorization|cookie|private[_-]?key|credential)", re.I)
_KEY = re.compile(
    r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b")
_BEARER = re.compile(r"(?i)\b(Bearer\s+|Basic\s+)[A-Za-z0-9+/_.=:-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_ASSIGNMENT = re.compile(
    r"(?i)(\b[\w.-]*(?:password|passwd|secret|token|api[_-]?key)[\w.-]*\s*[=:]\s*)"
    r"(\"[^\"\n]*\"|'[^'\n]*'|[^\s&,;]+)")
_URL_AUTH = re.compile(r"(https?://|ssh://)([^\s/@]+(?::[^\s/@]*)?@)", re.I)
_PRIVATE = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]*PRIVATE KEY)-----.*?"
    r"-----END (?:[A-Z0-9 ]*PRIVATE KEY)-----", re.S)


class Redactor:
    def __init__(self, secrets=()):
        # Longest first prevents a shorter known credential leaving a suffix behind.
        self.secrets = sorted({value for value in secrets if isinstance(value, str) and value}, key=len, reverse=True)

    def text(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, REDACTED)
        value = _PRIVATE.sub(REDACTED, value)
        value = _KEY.sub(REDACTED, value)
        value = _JWT.sub(REDACTED, value)
        value = _BEARER.sub(lambda match: match[1] + REDACTED, value)
        value = _URL_AUTH.sub(lambda match: match[1] + REDACTED + "@", value)
        return _ASSIGNMENT.sub(lambda match: match[1] + REDACTED, value)

    def clean(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {str(key): REDACTED if _SENSITIVE.search(str(key)) else self.clean(item)
                    for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(item) for item in value]
        return value
