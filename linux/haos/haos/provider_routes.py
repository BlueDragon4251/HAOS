"""Owner-selected, credential-isolated provider routes and explicit failover.

Version 1 policies remain byte-for-byte compatible. Version 2 keeps several
routes simultaneously; the caller cannot supply URLs, headers or credentials.
"""
from __future__ import annotations

import re
from .provider_policy import BASE, ProviderPolicy

_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")


class ProviderRoutes:
    def __init__(self, data):
        if not isinstance(data, dict):
            raise ValueError("invalid provider configuration")
        self.data = data
        self.ensembles, self.default_ensemble = {}, None
        if data.get("version") == 1:
            self.routes = {"default": ProviderPolicy(data)}
            self.default = "default"
            self.fallbacks = {}
            return
        required = {"version", "default", "routes", "fallbacks"}
        if (set(data) not in (required, required | {"ensembles", "default_ensemble"}) or type(data["version"]) is not int
                or data["version"] != 2 or not isinstance(data["routes"], dict)
                or not 1 <= len(data["routes"]) <= 32
                or any(not isinstance(key, str) or not _ID.fullmatch(key) for key in data["routes"])):
            raise ValueError("unsupported provider routes")
        self.routes = {key: ProviderPolicy(value) for key, value in data["routes"].items()}
        self.default = data["default"]
        if not isinstance(self.default, str) or self.default not in self.routes:
            raise ValueError("default route must be configured")
        self.fallbacks = data["fallbacks"]
        if not isinstance(self.fallbacks, dict) or set(self.fallbacks) - self.routes.keys():
            raise ValueError("invalid fallback routes")
        for key, targets in self.fallbacks.items():
            if (not isinstance(targets, list) or len(targets) > 4 or any(not isinstance(t, str) for t in targets)
                    or len(set(targets)) != len(targets) or key in targets or set(targets) - self.routes.keys()):
                raise ValueError("invalid fallback route")
            if any(self.routes[target].api_mode != self.routes[key].api_mode for target in targets):
                raise ValueError("fallback must preserve the native wire protocol")
        self.ensembles = data.get("ensembles", {})
        self.default_ensemble = data.get("default_ensemble")
        if (not isinstance(self.ensembles, dict) or len(self.ensembles) > 16
                or (self.default_ensemble is not None and self.default_ensemble not in self.ensembles)):
            raise ValueError("invalid owner MoA presets")
        for name, ensemble in self.ensembles.items():
            if (not isinstance(name, str) or not _ID.fullmatch(name) or not isinstance(ensemble, dict)
                    or set(ensemble) != {"references", "aggregator"}
                    or not isinstance(ensemble["references"], list) or not 1 <= len(ensemble["references"]) <= 2):
                raise ValueError("MoA requires a named preset with one or two bounded reference calls")
            for slot in [*ensemble["references"], ensemble["aggregator"]]:
                if (not isinstance(slot, dict) or set(slot) != {"route", "model"}
                        or not isinstance(slot["route"], str) or slot["route"] not in self.routes
                        or slot["model"] not in self.routes[slot["route"]].models):
                    raise PermissionError("MoA may use only configured broker routes and owner-approved models")

    @property
    def primary(self):
        return self.routes[self.default]

    def resolve(self, path):
        if path.startswith("/routes/"):
            parts = path.split("/", 3)
            if len(parts) != 4 or parts[2] not in self.routes:
                raise PermissionError("provider route is outside owner policy")
            return parts[2], "/" + parts[3]
        return self.default, path

    def client_config(self):
        if self.data["version"] == 1:
            return self.primary.client_config()
        config = self.primary.client_config()
        for key, policy in self.routes.items():
            route = dict(policy.client_config()["providers"]["haos-model"])
            route["base_url"] = BASE.removesuffix("/v1") + "/routes/" + key + "/v1"
            config["providers"]["haos-" + key] = route
        if self.ensembles:
            def slot(value):
                return {"provider": "custom:haos-" + value["route"], "model": value["model"], "enabled": True}
            presets = {name: {"reference_models": [slot(item) for item in value["references"]],
                              "aggregator": slot(value["aggregator"]), "enabled": True,
                              "reference_timeout": 180, "fanout": "user_turn"}
                       for name, value in self.ensembles.items()}
            # Hermes deep-merges its defaults. Explicitly overwrite its shipped
            # default preset with an approved route-only preset as well.
            presets.setdefault("default", next(iter(presets.values())))
            chosen = self.default_ensemble or next(iter(self.ensembles))
            config["moa"] = {"presets": presets, "default_preset": chosen, "active_preset": chosen,
                             "save_traces": False, "privacy_filter": "full"}
            if self.default_ensemble:
                config["model"] = {"provider": "moa", "default": chosen, "api_mode": "chat_completions"}
        # Preserve the established main alias; it selects the current owner
        # default while all named routes remain available to Hermes.
        return config


def load_provider(data):
    return ProviderRoutes(data)
