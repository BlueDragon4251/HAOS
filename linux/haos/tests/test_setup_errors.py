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
