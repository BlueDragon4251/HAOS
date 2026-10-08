"""Real diskless QEMU probes, distinct from installed-OS acceptance."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("qemu_runtime", Path(__file__).parents[3] / "scripts/haos-qemu-runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def test_real_tcg_machine_initializes():
    result = runtime.probe("tcg,thread=multi")
    print(json.dumps(result))
    assert result["usable"], result


def test_real_acceleration_selection():
    selected = runtime.select()
    print(json.dumps(selected))
    assert selected["accelerator"] in ("kvm", "tcg,thread=multi"), selected
    assert selected["attempts"][-1]["usable"]
