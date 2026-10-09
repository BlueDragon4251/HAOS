"""Bounded read-only system measurements; no repair or host-command endpoint."""

import math
from pathlib import Path
import shutil
import subprocess
import time

UNITS = ("haos-hermes.service", "haos-controller.service", "haos-policy.service",
         "haos-network.service", "haos-owner-ready.service", "haos-recovery.service",
         "haos-gateway.service", "haos-provider.service", "greetd.service")
DISKS = {"system": Path("/"), "workspace": Path("/var/lib/haos-workspace"), "missions": Path("/var/lib/haos-control")}
RESERVE_BYTES = 256 * 1024 * 1024
RESERVE_MEMORY = 64 * 1024 * 1024


class HealthSampler:
    def __init__(self):
        self.cpu = None

    def sample(self):
        errors, alerts = [], []
        value = {"at": time.time(), "status": "ok", "cpu_busy_percent": None,
                 "memory": None, "disks": {}, "temperatures": [], "gpus": [], "services": [],
                 "errors": errors, "alerts": alerts, "can_dispatch": False}
        try:
            fields = Path("/proc/stat").read_text().splitlines()[0].split()
            if fields[0] != "cpu" or len(fields) < 9:
                raise ValueError("invalid CPU counters")
            ticks = [int(field) for field in fields[1:9]]
            if min(ticks) < 0:
                raise ValueError("negative CPU counters")
            total, idle = sum(ticks), ticks[3] + ticks[4]
            if self.cpu is not None:
                delta, idle_delta = total - self.cpu[0], idle - self.cpu[1]
                if delta > 0 and 0 <= idle_delta <= delta:
                    value["cpu_busy_percent"] = round(100 * (delta - idle_delta) / delta, 1)
            self.cpu = (total, idle)
        except (OSError, ValueError, IndexError):
            errors.append("cpu")
        try:
            memory = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                name, *rest = line.split()
                if name in {"MemTotal:", "MemAvailable:"}:
                    if len(rest) != 2 or rest[1] != "kB":
                        raise ValueError("invalid memory measurement")
                    memory[name[:-1]] = int(rest[0]) * 1024
            if not 0 <= memory["MemAvailable"] <= memory["MemTotal"] or not memory["MemTotal"]:
                raise ValueError("invalid memory counters")
            value["memory"] = {"total": memory["MemTotal"], "available": memory["MemAvailable"]}
            if memory["MemAvailable"] < RESERVE_MEMORY:
                alerts.append("memory-reserve")
        except (OSError, ValueError, KeyError):
            errors.append("memory")
        for label, path in DISKS.items():
            try:
                disk = shutil.disk_usage(path)
                if not 0 <= disk.free <= disk.total or disk.total <= 0:
                    raise ValueError("invalid filesystem counters")
                value["disks"][label] = {"total": disk.total, "free": disk.free}
                if disk.free < RESERVE_BYTES:
                    alerts.append("disk-reserve:" + label)
            except (OSError, ValueError):
                errors.append("disk:" + label)
        # Optional hardware measurements remain absent when the kernel/driver
        # does not expose them. No fabricated CPU/GPU/temperature values.
        try:
            for sensor in sorted(Path("/sys/class/hwmon").glob("hwmon*"))[:16]:
                for input_path in sorted(sensor.glob("temp[0-9]*_input"))[:16]:
                    try:
                        temperature = int(input_path.read_text()) / 1000
                        if not math.isfinite(temperature) or not -100 <= temperature <= 250:
                            continue
                        row = {"sensor": f"{sensor.name}/{input_path.stem}", "celsius": temperature}
                        limit = input_path.with_name(input_path.name.replace("_input", "_crit"))
                        if limit.exists():
                            critical = int(limit.read_text()) / 1000
                            if 0 < critical <= 250:
                                row["critical_celsius"] = critical
                                if temperature >= critical:
                                    alerts.append("temperature:" + row["sensor"])
                        value["temperatures"].append(row)
                    except (OSError, ValueError):
                        continue
            for card in sorted(Path("/sys/class/drm").glob("card[0-9]"))[:16]:
                try:
                    busy = int((card / "device/gpu_busy_percent").read_text())
                    if 0 <= busy <= 100:
                        value["gpus"].append({"device": card.name, "busy_percent": busy})
                except (OSError, ValueError):
                    continue
        except OSError:
            errors.append("sensors")
        try:
            reply = subprocess.run(["/usr/bin/systemctl", "show", "--no-pager",
                                    "--property=Id,LoadState,ActiveState,SubState,MemoryCurrent,CPUUsageNSec,TasksCurrent,Result", *UNITS],
                                   capture_output=True, text=True, timeout=3,
                                   env={"PATH": "/usr/bin:/bin", "LANG": "C", "SYSTEMD_COLORS": "0"})
            if reply.returncode or len(reply.stdout) > 32768:
                raise ValueError("service metadata unavailable")
            for block in reply.stdout.strip().split("\n\n"):
                properties = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
                if properties.get("Id") not in UNITS:
                    continue
                row = {"unit": properties["Id"], "active": properties.get("ActiveState", "unknown"),
                       "state": properties.get("SubState", "unknown")}
                for key, output in (("MemoryCurrent", "memory_bytes"), ("CPUUsageNSec", "cpu_nanoseconds"), ("TasksCurrent", "tasks")):
                    number = properties.get(key, "")
                    if number.isdecimal() and 0 <= int(number) < 2 ** 63:
                        row[output] = int(number)
                value["services"].append(row)
                if row["active"] == "failed":
                    alerts.append("service:" + row["unit"])
        except (OSError, ValueError, subprocess.TimeoutExpired):
            errors.append("services")
        # Health errors and pressure pause NEW dispatch only. They never repeat
        # or kill an uncertain action, modify policy or delete recovery state.
        pressure = any(alert.startswith(("memory-reserve", "disk-reserve:", "temperature:")) for alert in alerts)
        storage_unknown = any(error.startswith("disk:") or error == "memory" for error in errors)
        value["can_dispatch"] = not pressure and not storage_unknown
        value["status"] = "critical" if pressure else "degraded" if alerts or errors else "ok"
        return value
