#!/usr/bin/env python3
"""Probe actual QEMU acceleration as the caller, before opening fixture disks."""
import argparse
import json
from pathlib import Path
import subprocess


def probe(accelerator: str, run=subprocess.run) -> dict:
    args = ["qemu-system-x86_64", "-machine", "q35", "-nodefaults",
            "-display", "none", "-m", "128", "-smp", "2", "-S",
            "-accel", accelerator, "-cpu", "host" if accelerator == "kvm" else "max",
            "-qmp", "stdio"]
    try:
        result = run(args, input='{"execute":"qmp_capabilities"}\n{"execute":"quit"}\n',
                     text=True, capture_output=True, timeout=30, check=False)
        replies = []
        for line in result.stdout.splitlines():
            try:
                replies.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        # A return code alone is not proof that a VM was instantiated.
        ready = any(isinstance(reply, dict) and "QMP" in reply for reply in replies)
        returns = sum(isinstance(reply, dict) and "return" in reply for reply in replies)
        return {"accelerator": accelerator, "usable": result.returncode == 0 and ready and returns == 2,
                "returncode": result.returncode, "stderr": result.stderr[-8192:]}
    except subprocess.TimeoutExpired:
        return {"accelerator": accelerator, "usable": False, "error": "probe timed out after 30 seconds"}


def select(probe_vm=probe) -> dict:
    # Recheck every phase: /dev/kvm permissions can change after an earlier boot.
    attempts = [probe_vm("kvm")]
    if attempts[0]["usable"]:
        return {"accelerator": "kvm", "cpu": "host", "attempts": attempts}
    attempts.append(probe_vm("tcg,thread=multi"))
    if not attempts[1]["usable"]:
        return {"accelerator": None, "attempts": attempts}
    return {"accelerator": "tcg,thread=multi", "cpu": "max", "attempts": attempts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    evidence = select()
    args.evidence.write_text(json.dumps(evidence, indent=2) + "\n")
    if evidence["accelerator"] is None:
        raise SystemExit("Neither KVM nor TCG can initialize QEMU; see " + str(args.evidence))
    print("-accel", evidence["accelerator"], "-cpu", evidence["cpu"], sep="\n")


if __name__ == "__main__":
    main()
