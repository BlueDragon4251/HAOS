"""Run the canonical Hermes serve CLI with an image-owned observer middleware."""
import os
from pathlib import Path
import sys

# The launcher uses this immutable installed file under the pinned runtime's
# Python; no writable agent directory supplies the middleware or startup code.
if __package__:
    from .web_access import DashboardAccess, TOKEN
else:
    from web_access import DashboardAccess, TOKEN


def run(backend, observer, *, port=9119, isolated=False):
    if not TOKEN.fullmatch(backend) or not TOKEN.fullmatch(observer) or backend == observer:
        raise ValueError("invalid dashboard capabilities")
    os.environ["HERMES_DASHBOARD_SESSION_TOKEN"] = backend
    os.environ["HERMES_SERVE_HEADLESS"] = "1"
    if __package__:
        from .startup import StartupDiagnosis
    else:
        from startup import StartupDiagnosis
    diagnosis=StartupDiagnosis(port)
    with diagnosis:
        return canonical_run(backend,observer,port,isolated,diagnosis)


def canonical_run(backend,observer,port,isolated,diagnosis):
    diagnosis.mark('web-import')
    from hermes_cli.web_server import app
    # HAOS supplies a scoped tool through the public registry; upstream is unmodified.
    if __package__:
        from .gui_tool import register
    else:
        from gui_tool import register
    diagnosis.mark('gui-registration')
    register()
    scoped = os.environ.get("HAOS_MODEL_TOKEN", "")
    app.add_middleware(DashboardAccess, backend_token=backend, observer_token=observer,
                       redact_tokens=[scoped] if scoped else [])
    diagnosis.mark('cli-import')
    from hermes_cli.main import main as hermes_main
    sys.argv = ["hermes", "serve", "--host", "127.0.0.1", "--port", str(port), "--no-open"]
    if isolated:
        sys.argv.append("--isolated")
    diagnosis.mark('canonical-cli')
    hermes_main()
    diagnosis.mark('returned')


def main():
    root = Path("/run/haos-credentials")
    run((root / "backend-token").read_text().strip(), (root / "ui-token").read_text().strip())


if __name__ == "__main__":
    main()
