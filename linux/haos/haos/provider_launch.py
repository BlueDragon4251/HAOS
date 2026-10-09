"""Preserve activation descriptors when entering the immutable Hermes interpreter."""

import os


if __name__ == "__main__":
    executable = "/usr/lib/haos/hermes/.venv/bin/python"
    os.execv(executable, [executable, "-m", "haos.provider_proxy"])
