import pytest

from haos.model_router import Candidate, Task, Mode, select, fallback


def model(provider, name, caps, privacy="cloud", quality=70, latency=1000, price=1,
          enabled=True, reachable=True):
    return Candidate(provider, name, frozenset(caps), privacy, quality,
                     latency, price, enabled, reachable)


def test_balanced_quality_and_price_preference():
    a = model("local", "fast", {"chat", "coding"}, "local", 58, 300, 0)
    b = model("cloud", "strong", {"chat", "coding"}, quality=98, latency=600, price=5)
    task = Task(frozenset({"coding"}))
    assert select([a, b], task, Mode.QUALITY) == b
    assert select([a, b], task, Mode.LOW_COST) == a


def test_vision_never_routed_to_text_model():
    text = model("local", "text", {"chat", "coding"}, "local")
    vision = model("vision", "v1", {"chat", "vision"})
    assert select([text, vision], Task(frozenset({"vision"}))) == vision


def test_owner_provider_approval_is_required():
    primary = model("allowed", "one", {"chat"})
    other = model("foreign", "two", {"chat"}, quality=100)
    assert select([other, primary], Task(frozenset({"chat"}), allowed_providers=frozenset({"allowed"}))) == primary


def test_private_or_offline_data_never_leak_into_cloud():
    cloud = model("cloud", "excellent", {"chat"}, quality=100)
    local = model("local", "safe", {"chat"}, privacy="local", quality=50)
    restricted = Task(frozenset({"chat"}), max_privacy="local", offline=True)
    assert select([cloud, local], restricted) == local
    with pytest.raises(PermissionError):
        fallback([cloud, local], restricted, {("local", "safe")})


def test_no_select_when_unreachable_or_disabled():
    off = model("local", "offline", {"chat"}, reachable=False)
    denied = model("cloud", "disabled", {"chat"}, enabled=False)
    with pytest.raises(PermissionError):
        select([off, denied], Task(frozenset({"chat"})))


def test_cost_ceiling_and_quality_floor_are_enforced():
    costly = model("cloud", "expensive", {"coding"}, quality=100, price=40)
    cheap = model("cloud", "cheap", {"coding"}, quality=60, price=1)
    t = Task(frozenset({"coding"}), min_quality=70, max_input_usd_per_million=3)
    with pytest.raises(PermissionError):
        select([costly, cheap], t)


def test_reject_untrusted_registration_and_task_payloads():
    with pytest.raises(ValueError):
        model("provider;rm", "x", {"chat"})
    with pytest.raises(ValueError):
        model("provider", "x", {"root-exec"})
    with pytest.raises(ValueError):
        model("provider", "x", {"chat"}, price=float("nan"))
    with pytest.raises(ValueError):
        Task(frozenset({"chat"}), max_privacy="unrestricted")
    with pytest.raises(ValueError):
        Task(frozenset({"chat"}), max_input_usd_per_million=-1)
    with pytest.raises(ValueError):
        select([], Task(frozenset({"chat"})), "bypass")


def test_routing_is_deterministic_for_equal_models():
    first = model("a", "m", {"chat"})
    second = model("b", "m", {"chat"})
    t = Task(frozenset({"chat"}))
    assert select([second, first], t) == select([first, second], t) == first
