"""Deterministic privacy-aware Hermes multi-model selection policy.

This is a pure decision engine. It never opens provider sockets, changes
credentials or grants capabilities. Provider registration and dispatch require
a separate owner-authorized integration and acceptance test.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Iterable

_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_./:-]{0,127}\Z")
_CAPABILITIES = frozenset({"chat", "coding", "vision", "tools", "long-context", "audio"})
_PRIVACY = {"local": 0, "trusted-cloud": 1, "cloud": 2}


class Mode(str, Enum):
    BALANCED = "balanced"
    QUALITY = "quality"
    SPEED = "speed"
    LOW_COST = "low-cost"


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str
    capabilities: frozenset[str]
    privacy: str  # local, trusted-cloud, cloud
    quality: int  # normalized comparative rating, 0..100, never a promise
    latency_ms: int  # observed rolling estimate
    usd_per_million_input: float
    enabled: bool = False
    reachable: bool = False

    def __post_init__(self):
        if (not _NAME.fullmatch(self.provider) or not _NAME.fullmatch(self.model)
                or self.privacy not in _PRIVACY or not self.capabilities
                or not self.capabilities <= _CAPABILITIES or not 0 <= self.quality <= 100
                or not 1 <= self.latency_ms <= 600000
                or not math.isfinite(self.usd_per_million_input)
                or not 0 <= self.usd_per_million_input <= 10000):
            raise ValueError("invalid untrusted model registry entry")


@dataclass(frozen=True)
class Task:
    capabilities: frozenset[str]
    max_privacy: str = "cloud"
    allowed_providers: frozenset[str] = frozenset()
    max_input_usd_per_million: float | None = None
    min_quality: int = 0
    offline: bool = False

    def __post_init__(self):
        if (not self.capabilities or not self.capabilities <= _CAPABILITIES
                or self.max_privacy not in _PRIVACY
                or not 0 <= self.min_quality <= 100
                or any(not _NAME.fullmatch(p) for p in self.allowed_providers)
                or (self.max_input_usd_per_million is not None
                    and (not math.isfinite(self.max_input_usd_per_million)
                         or self.max_input_usd_per_million < 0))):
            raise ValueError("invalid model routing task")


def eligible(model: Candidate, task: Task) -> bool:
    return (model.enabled and model.reachable
            and task.capabilities <= model.capabilities
            and _PRIVACY[model.privacy] <= _PRIVACY[task.max_privacy]
            and (not task.offline or model.privacy == "local")
            and (not task.allowed_providers or model.provider in task.allowed_providers)
            and model.quality >= task.min_quality
            and (task.max_input_usd_per_million is None
                 or model.usd_per_million_input <= task.max_input_usd_per_million))


def score(model: Candidate, mode: Mode) -> float:
    # Explicitly cap each independent normalized term. Do not accidentally
    # rank an unavailable/unauthorized model: eligibility is checked first.
    quality = model.quality / 100
    speed = 1 / (1 + model.latency_ms / 2000)
    affordable = 1 / (1 + model.usd_per_million_input / 3)
    weights = {
        Mode.BALANCED: (0.45, 0.25, 0.30),
        Mode.QUALITY: (0.80, 0.10, 0.10),
        Mode.SPEED: (0.10, 0.80, 0.10),
        Mode.LOW_COST: (0.10, 0.10, 0.80),
    }
    a, b, c = weights[mode]
    return quality * a + speed * b + affordable * c


def select(models: Iterable[Candidate], task: Task, mode: Mode = Mode.BALANCED) -> Candidate:
    """Fail closed. Unavailable models or privacy-incompatible fallbacks are never selected."""
    if not isinstance(mode, Mode):
        raise ValueError("unsupported routing policy")
    allowed = [model for model in models if eligible(model, task)]
    if not allowed:
        raise PermissionError("no online, owner-approved model satisfies task permissions")
    return sorted(allowed, key=lambda c: (-score(c, mode), c.provider, c.model))[0]


def fallback(models: Iterable[Candidate], task: Task, excluded: set[tuple[str, str]],
             mode: Mode = Mode.BALANCED) -> Candidate:
    """Never silently retry on a privacy-disallowed provider after an outage."""
    available = [m for m in models if (m.provider, m.model) not in excluded]
    return select(available, task, mode)
