"""Render greedy and Z3 patch-rotation schedules for the smallest benchmark."""

from pathlib import Path

from qiskit import qasm2

from ftqc_patch_rotation import greedy_optimize, preprocess, sat_optimize
from ftqc_patch_rotation.schedule import build_schedule
from ftqc_patch_rotation.visualize import draw_schedule


ROOT = Path(__file__).parents[1]
INPUT = ROOT / "benchmarks" / "feynman_clifford" / "tof_3.qasm"
OUTPUT = ROOT / "visualizations" / "tof_3"


def main() -> None:
    circuit = qasm2.load(str(INPUT))
    prepared = preprocess(circuit)
    labels = tuple(
        f"{circuit.find_bit(qubit).registers[0][0].name}[{circuit.find_bit(qubit).registers[0][1]}]"
        for qubit in circuit.qubits
    )
    solutions = {
        "greedy": greedy_optimize(prepared),
        "z3": sat_optimize(prepared, timeout_s=60.0),
    }
    for name, rotations in solutions.items():
        schedule = build_schedule(prepared, rotations)
        path = draw_schedule(
            schedule,
            circuit.num_qubits,
            OUTPUT / f"tof_3_{name}.png",
            title=f"tof_3 — {name} ({len(rotations)} patch rotations)",
            qubit_labels=labels,
        )
        print(f"{name}: {len(rotations)} rotations, {len(schedule)} scheduled operations -> {path}")


if __name__ == "__main__":
    main()
