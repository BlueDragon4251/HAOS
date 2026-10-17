from haos.initial_setup_gui import session_allowed

def test_reject_remote_regular_users_and_reused_wayland_sessions():
    safe = {"HAOS_TRUSTED_SETUP": "1", "DISPLAY": ":8"}
    assert session_allowed(safe, uid=0)
    assert not session_allowed(safe, uid=1000)
    assert not session_allowed({**safe, "DISPLAY": ":0"}, uid=0)
    assert not session_allowed({**safe, "SSH_CONNECTION": "1 2 3 4"}, uid=0)
    assert not session_allowed({**safe, "WAYLAND_DISPLAY": "wayland-0"}, uid=0)
    assert not session_allowed({"DISPLAY": ":8"}, uid=0)
