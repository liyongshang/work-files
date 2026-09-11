"""Compare scheduler runtime against the saved pre-fix source, not correctness."""
import json
import statistics
import sys
import time
import types
from pathlib import Path

from qiskit import QuantumCircuit
from ftqc_patch_rotation import greedy_optimize, preprocess
from ftqc_patch_rotation.generator import random_layered_clifford_circuit
from ftqc_patch_rotation.schedule import build_schedule


def main():
    module = types.ModuleType("ftqc_patch_rotation._baseline")
    module.__package__ = "ftqc_patch_rotation"
    sys.modules[module.__name__] = module
    exec(Path("tmp/schedule_before_reset_fix.py").read_text(encoding="utf-8"), module.__dict__)
    rows = []
    for layers in (10, 50, 100):
        c = random_layered_clifford_circuit(10, layers, 20260908)
        p = preprocess(c)
        r = greedy_optimize(p)
        values = [[], []]
        for repeat in range(12):
            for i in ((0, 1) if repeat % 2 == 0 else (1, 0)):
                start = time.perf_counter()
                for _ in range(3):
                    (module.build_schedule if i == 0 else build_schedule)(p, r)
                if repeat:
                    values[i].append((time.perf_counter() - start) / 3)
        before, after = [statistics.median(v) for v in values]
        rows.append(dict(layers=layers, nodes=len(p.g1), rotations=len(r),
                         before_ms=before*1000, after_ms=after*1000,
                         change_percent=(after/before-1)*100))
    # The old result is incorrect for resets, so its runtime is not comparable work.
    c = QuantumCircuit(3)
    for _ in range(100):
        c.cz(0, 1)
        c.reset(0)
        c.cz(0, 2)
        c.reset(0)
    p = preprocess(c)
    r = greedy_optimize(p)
    start = time.perf_counter()
    out = build_schedule(p, r)
    reset_ms = (time.perf_counter() - start)*1000
    payload = dict(non_reset_comparison=rows, reset_case=dict(nodes=len(p.g1),
                   rotations=len(r), emitted_rotations=sum(o.kind == "rot" for o in out),
                   fixed_ms=reset_ms), note="Scheduler only; median of 11 alternating samples, 3 runs per sample. Optimizers unchanged.")
    dest = Path("outputs/framework/schedule_fix_benchmark.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
