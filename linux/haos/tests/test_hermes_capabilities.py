from pathlib import Path

from haos.hermes_capabilities import (
    PINNED_HERMES_SHA, HERMES_PROVIDERS, HERMES_PLATFORMS,
    HAOS_GUI_PROVIDERS, HAOS_GUI_GATEWAYS, provider_rows, gateway_rows,
)


def test_catalogue_is_pinned_and_complete():
    lock = Path(__file__).resolve().parents[3] / "upstream/UPSTREAM.lock"
    assert "sha=" + PINNED_HERMES_SHA in lock.read_text(encoding="utf-8")
    assert len(HERMES_PROVIDERS) == 53  # 39 regular entries + 14 registered profiles
    assert len(HERMES_PLATFORMS) == 22
    assert len({slug for slug, _ in HERMES_PROVIDERS}) == 53
    assert len(set(HERMES_PLATFORMS)) == 22
    assert HAOS_GUI_PROVIDERS <= {slug for slug, _ in HERMES_PROVIDERS}
    assert HAOS_GUI_GATEWAYS <= set(HERMES_PLATFORMS)


def test_ui_does_not_label_untested_adapters_as_supported():
    providers = {slug: status for slug, label, status in provider_rows()}
    gateways = dict(gateway_rows())
    assert providers["openai-codex"] == "GUI"
    assert providers["qwen-oauth"] == "GUI"
    assert providers["openai-api"] == "GUI"
    assert providers["anthropic"] == "GUI"
    assert providers["bedrock"] == "GUI"
    assert providers["gemini"] == "GUI"
    assert providers["copilot-acp"] == "GUI"
    assert gateways["telegram"] == "GUI"
    assert gateways["discord"] == "GUI"
    assert gateways['slack'] == 'GUI'
    for name in ("whatsapp", "matrix", "feishu", "email"):
        assert gateways[name] == "Nicht integriert"
