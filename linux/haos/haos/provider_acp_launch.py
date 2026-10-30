"""Preserve root-created socket activation descriptors across interpreter entry."""
import os

if __name__ == "__main__":
    executable = "/usr/lib/haos/hermes/.venv/bin/python"
    os.execv(executable, [executable, "-m", "haos.provider_acp"])
