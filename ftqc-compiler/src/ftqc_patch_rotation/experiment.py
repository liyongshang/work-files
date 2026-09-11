from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import matplotlib.pyplot as plt
from qiskit import qasm2

from .generator import random_deep_clifford_circuit
from .greedy import greedy_optimize
from .preprocess import preprocess
from .sat import SatTimeoutError
from .schedule import build_schedule
from .trivial import trivial_optimize
from .window_sat import sliding_window_sat_optimize
from .visualize import draw_schedule


def run_experiment(
    output_dir: str | Path,
    count: int = 10,
    num_qubits: int = 10,
    sat_timeout_s: float = 60.0,
    first_seed: int = 0,
    segments: int = 2,
    window_size: int = 20,
) -> list[dict[str, int | float]]:
    output_dir = Path(output_dir)
    circuits_dir = output_dir / "circuits"
    circuits_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, int | float]] = []
    seed = first_seed

    while len(rows) < count:
        try:
            circuit, segment_count = random_deep_clifford_circuit(
                num_qubits, seed, min_segments=segments, max_segments=segments
            )
            prepared = preprocess(circuit)
            trivial_start = time.perf_counter()
            trivial = trivial_optimize(prepared, seed=seed)
            trivial_time = time.perf_counter() - trivial_start
            greedy_start = time.perf_counter()
            greedy = greedy_optimize(prepared)
            greedy_time = time.perf_counter() - greedy_start
            window_start = time.perf_counter()
            window_solution = sliding_window_sat_optimize(
                prepared, window_size=window_size, timeout_s=sat_timeout_s
            )
            window_time = time.perf_counter() - window_start
        except (SatTimeoutError, RuntimeError):
            seed += 1
            continue

        index = len(rows)
        (circuits_dir / f"circuit_{index:02d}_seed_{seed}.qasm").write_text(
            qasm2.dumps(circuit), encoding="utf-8"
        )
        row = {
            "index": index,
            "seed": seed,
            "qubits": num_qubits,
            "segments": segment_count,
            "circuit_depth": circuit.depth(),
            "cz_gates": len(prepared.cz_nodes),
            "trivial_rotations": len(trivial),
            "greedy_rotations": len(greedy),
            "window_sat_rotations": len(window_solution),
            "trivial_over_window_sat": len(trivial) - len(window_solution),
            "greedy_over_window_sat": len(greedy) - len(window_solution),
            "trivial_time_s": trivial_time,
            "greedy_time_s": greedy_time,
            "window_sat_time_s": window_time,
        }
        rows.append(row)
        (output_dir / f"solutions_{index:02d}.json").write_text(
            json.dumps(
                {"trivial": trivial, "greedy": greedy, "window_sat": window_solution},
                indent=2,
            ),
            encoding="utf-8",
        )
        if index == 0:
            schedule = build_schedule(prepared, window_solution)
            draw_schedule(schedule, num_qubits, output_dir / "first_circuit.png")
        seed += 1

    fieldnames = list(rows[0]) if rows else []
    with (output_dir / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    _draw_comparison(rows, output_dir / "rotation_comparison.png")
    return rows


def _draw_comparison(rows: list[dict[str, int | float]], output: Path) -> None:
    x = list(range(1, len(rows) + 1))
    width = 0.38
    fig, ax = plt.subplots(figsize=(max(7, len(rows) * 0.7), 4.5))
    width = 0.25
    ax.bar([value - width for value in x], [row["trivial_rotations"] for row in rows], width, label="Trivial random")
    ax.bar(x, [row["greedy_rotations"] for row in rows], width, label="Greedy")
    ax.bar(
        [value + width for value in x],
        [row["window_sat_rotations"] for row in rows],
        width,
        label="Sliding-window SAT",
    )
    ax.set_xlabel("Circuit")
    ax.set_ylabel("Patch rotations")
    ax.set_xticks(x)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--qubits", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--segments", type=int, default=2)
    parser.add_argument("--window-size", type=int, default=20)
    args = parser.parse_args()
    run_experiment(
        args.output,
        args.count,
        args.qubits,
        args.timeout,
        args.seed,
        args.segments,
        args.window_size,
    )


if __name__ == "__main__":
    main()
