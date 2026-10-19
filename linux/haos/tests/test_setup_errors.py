import subprocess
from haos.setup_errors import describe_error

def test_safe_diagnostics():
    mismatch = describe_error(ValueError("Administrator passwords do not match"), area="security")
    assert "stimmen nicht" in mismatch.title
    low = describe_error(RuntimeError("owner enrollment command failed: /usr/bin/pwscore"))
    assert "pwscore" in low.title
    stopped = describe_error(subprocess.CalledProcessError(
        7, ["/usr/bin/systemctl", "stop", "haos-gateway.service",
        "haos-controller.service", "haos-hermes.service"]))
    assert stopped.code == "HAOS-OWNER-STOP"
    assert "7" in stopped.details

def test_untrusted_exception_is_not_displayed():
    private = "untrusted_user_input_123"
    result = describe_error(ValueError(private))
    assert private not in result.title + result.details

def test_observer_permission_causes_are_identified_without_raw_paths():
    from haos.setup_errors import SetupStageError
    for message, expected in (
        ("unsafe observer configuration directory", "HAOS-PROFILE-PERMISSIONS"),
        ("unexpected HAOS observer account", "HAOS-PROFILE-ACCOUNT"),
        ("observer home not provisioned", "HAOS-PROFILE-HOME"),
        ("existing observer data must remain owned by its user", "HAOS-PROFILE-FILE-OWNER"),
    ):
        report = describe_error(SetupStageError("PROFILE", PermissionError(message)), area="user")
        assert report.code == expected
        assert report.title != "Die HAOS-Einrichtung konnte nicht abgeschlossen werden."

def test_region_stages_keep_root_causes_separate():
    from haos.setup_errors import SetupStageError
    system = describe_error(SetupStageError("REGION_SYSTEM", PermissionError("private")), area="region")
    observer = describe_error(SetupStageError("REGION_OBSERVER", PermissionError("private")), area="region")
    assert system.code == "HAOS-REGION-SYSTEM"
    assert observer.code == "HAOS-REGION-PROFILE"
    assert "private" not in system.details + observer.details
