"""Collect Qiskit width/depth/operation statistics for converted benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qiskit import qasm2


def collect(directory: Path) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    for path in sorted(directory.rglob("*.qasm")):
        circuit = qasm2.load(str(path))
        counts = dict(circuit.count_ops())
        resource_qubits = sum(
            register.size
            for register in circuit.qregs
            if register.name in {"cczreg", "treg"}
        )
        measurements = counts.get("measure", 0)
        resets = counts.get("reset", 0)
        rows.append(
            {
                "circuit": path.relative_to(directory).as_posix(),
                "total_qubits": circuit.num_qubits,
                "data_qubits": circuit.num_qubits - resource_qubits,
                "resource_qubits": resource_qubits,
                "depth": circuit.depth(),
                "gate_count": circuit.size(),
                "clifford_unitary_gates": circuit.size() - measurements - resets,
                "measurements": measurements,
                "resets": resets,
                "h": counts.get("h", 0),
                "x": counts.get("x", 0),
                "z": counts.get("z", 0),
                "s": counts.get("s", 0),
                "sdg": counts.get("sdg", 0),
                "cx": counts.get("cx", 0),
                "cz": counts.get("cz", 0),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", type=Path, default=Path("benchmarks/feynman_clifford")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/feynman_clifford_stats.json")
    )
    args = parser.parse_args()
    rows = collect(args.input)
    args.output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
