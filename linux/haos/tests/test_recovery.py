from haos.store import MissionStore


def test_repeated_pre_dispatch_crashes_exhaust_the_retry_budget(tmp_path):
    path = tmp_path / "missions.db"
    store = MissionStore(path)
    row = store.create("uid:1000", "a", "Build", max_attempts=1)
    assert store.claim()
    store.close()
    restarted = MissionStore(path)
    restarted.recover()
    assert restarted.get(row["id"])["state"] == "failed"
    assert restarted.claim() is None
    restarted.close()
