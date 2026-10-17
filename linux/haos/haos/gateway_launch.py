"""Use the immutable Hermes interpreter without depending on it during unit syntax checks."""

import os


def main():
    executable = "/usr/lib/haos/hermes/.venv/bin/python"
    os.execv(executable, [executable, "-m", "haos.gateway_runtime"])


if __name__ == "__main__":
    main()
