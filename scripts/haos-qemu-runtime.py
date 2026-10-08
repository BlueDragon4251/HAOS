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


def run_guest(args, serial_log: Path, timeout: int, *, run=subprocess.run, probe_vm=probe):
    evidence = select(probe_vm)
    evidence["launches"] = []
    if evidence["accelerator"] is None:
        return evidence, 1
    for attempt in range(2):
        accelerator = evidence["accelerator"]
        command = ["qemu-system-x86_64", "-accel", accelerator, "-cpu", evidence["cpu"], *args]
        print("Launching VM with " + accelerator, flush=True)
        try:
            result = run(command, text=True, capture_output=True, timeout=timeout, check=False)
            code, stderr = result.returncode, result.stderr[-8192:]
        except subprocess.TimeoutExpired:
            code, stderr = 124, "VM phase timed out"
        evidence["launches"].append({"accelerator": accelerator, "returncode": code, "stderr": stderr})
        serial_empty = not serial_log.exists() or serial_log.stat().st_size == 0
        # A successful preflight can race with runner/device policy changes. Retry
        # only an explicit KVM initialization failure with no guest output.
        if not (attempt == 0 and accelerator == "kvm" and code == 1 and serial_empty
                and "failed to initialize kvm:" in stderr):
            return evidence, code if code >= 0 else 1
        fallback = probe_vm("tcg,thread=multi")
        evidence["attempts"].append(fallback)
        if not fallback["usable"]:
            return evidence, 1
        evidence["accelerator"], evidence["cpu"] = "tcg,thread=multi", "max"
        evidence["fallback_reason"] = "actual KVM initialization failed before guest output"
    raise AssertionError("unreachable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--serial-log", type=Path)
    parser.add_argument("qemu_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.run:
        if args.timeout is None or args.timeout <= 0 or args.serial_log is None:
            parser.error("--run requires positive --timeout and --serial-log")
        qemu_args = args.qemu_args[1:] if args.qemu_args[:1] == ["--"] else args.qemu_args
        evidence, code = run_guest(qemu_args, args.serial_log, args.timeout)
        args.evidence.write_text(json.dumps(evidence, indent=2) + "\n")
        if code:
            print(json.dumps(evidence["launches"]), flush=True)
        raise SystemExit(code)
    evidence = select()
    args.evidence.write_text(json.dumps(evidence, indent=2) + "\n")
    if evidence["accelerator"] is None:
        raise SystemExit("Neither KVM nor TCG can initialize QEMU; see " + str(args.evidence))
    print("-accel", evidence["accelerator"], "-cpu", evidence["cpu"], sep="\n")


if __name__ == "__main__":
    main()
