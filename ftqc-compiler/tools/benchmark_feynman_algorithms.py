"""Benchmark rotation optimizers on the converted Feynman circuit suite."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import matplotlib.pyplot as plt
from qiskit import qasm2

from ftqc_patch_rotation import (
    SatTimeoutError,
    greedy_optimize,
    preprocess,
    simulate_rotations,
    sliding_window_sat_optimize,
    trivial_optimize,
)


def _run_base(prepared, seed: int) -> dict[str, int | float]:
    started = time.perf_counter()
    trivial = trivial_optimize(prepared, seed=seed)
    trivial_s = time.perf_counter() - started
    print(f"  trivial finished in {trivial_s:.2f}s", flush=True)
    started = time.perf_counter()
    greedy = greedy_optimize(prepared)
    greedy_s = time.perf_counter() - started
    print(f"  greedy finished in {greedy_s:.2f}s", flush=True)
    if not simulate_rotations(prepared, trivial).complete:
        raise RuntimeError("trivial returned an incomplete solution")
    if not simulate_rotations(prepared, greedy).complete:
        raise RuntimeError("greedy returned an incomplete solution")
    return {
        "trivial_rotations": len(trivial),
        "greedy_rotations": len(greedy),
        "trivial_time_s": trivial_s,
        "greedy_time_s": greedy_s,
    }


def _plot(rows: list[dict], algorithms: list[tuple[str, str]], output: Path) -> None:
    if not rows:
        return
    x = list(range(len(rows)))
    width = 0.8 / len(algorithms)
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.62), 6.5))
    for index, (key, label) in enumerate(algorithms):
        offset = (index - (len(algorithms) - 1) / 2) * width
        ax.bar(
            [value + offset for value in x],
            [row[key] for row in rows],
            width,
            label=label,
        )
    ax.set_yscale("symlog", linthresh=10)
    ax.set_ylabel("Patch rotations (symlog scale)")
    ax.set_xticks(x, [Path(row["circuit"]).stem for row in rows], rotation=55, ha="right")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def run(input_dir: Path, stats_path: Path, output_dir: Path, timeout_s: float) -> list[dict]:
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = output_dir / "results.json"
    rows: list[dict] = (
        json.loads(checkpoint.read_text(encoding="utf-8"))
        if checkpoint.exists()
        else []
    )
    completed_names = {row["circuit"] for row in rows}

    for index, item in enumerate(stats):
        if item["circuit"] in completed_names:
            print(f"[{index + 1}/{len(stats)}] {item['circuit']} resumed from checkpoint", flush=True)
            continue
        path = input_dir / item["circuit"]
        eligible = item["data_qubits"] <= 20
        print(
            f"[{index + 1}/{len(stats)}] {item['circuit']} "
            f"data_qubits={item['data_qubits']} eligible_sat={eligible}",
            flush=True,
        )
        circuit = qasm2.load(str(path))
        prep_started = time.perf_counter()
        prepared = preprocess(circuit)
        print(
            f"  preprocess finished in {time.perf_counter() - prep_started:.2f}s "
            f"({len(prepared.cz_nodes)} CZ nodes)",
            flush=True,
        )
        row = {
            "circuit": item["circuit"],
            "data_qubits": item["data_qubits"],
            "total_qubits": item["total_qubits"],
            "depth": item["depth"],
            "gate_count": item["gate_count"],
            "cz_nodes": len(prepared.cz_nodes),
            "preprocess_time_s": time.perf_counter() - prep_started,
            "sat_eligible": eligible,
            "sat_status": "not_eligible",
            "window_sat_rotations": None,
            "window_sat_time_s": None,
        }
        row.update(_run_base(prepared, seed=20260826 + index))

        if eligible:
            started = time.perf_counter()
            try:
                solution = sliding_window_sat_optimize(
                    prepared, window_size=20, timeout_s=timeout_s
                )
                elapsed = time.perf_counter() - started
                if not simulate_rotations(prepared, solution).complete:
                    raise RuntimeError("window SAT returned an incomplete solution")
                row["sat_status"] = "completed"
                row["window_sat_rotations"] = len(solution)
                row["window_sat_time_s"] = elapsed
            except SatTimeoutError:
                row["sat_status"] = "timeout"
                row["window_sat_time_s"] = time.perf_counter() - started
                print(f"  SAT timeout after {row['window_sat_time_s']:.2f}s", flush=True)

        rows.append(row)
        checkpoint.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(
            f"  rotations trivial={row['trivial_rotations']} "
            f"greedy={row['greedy_rotations']} "
            f"sat={row['window_sat_rotations']} ({row['sat_status']})",
            flush=True,
        )

    fieldnames = list(rows[0])
    with (output_dir / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    completed = [row for row in rows if row["sat_status"] == "completed"]
    remaining = [row for row in rows if row["sat_status"] != "completed"]
    _plot(
        completed,
        [
            ("trivial_rotations", "Trivial"),
            ("greedy_rotations", "Greedy"),
            ("window_sat_rotations", "Sliding-window SAT"),
        ],
        output_dir / "eligible_completed_rotation_comparison.png",
    )
    _plot(
        remaining,
        [
            ("trivial_rotations", "Trivial"),
            ("greedy_rotations", "Greedy"),
        ],
        output_dir / "other_and_timeout_rotation_comparison.png",
    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("benchmarks/feynman_clifford"))
    parser.add_argument(
        "--stats", type=Path, default=Path("benchmarks/feynman_clifford_stats.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results_feynman_algorithms")
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    run(args.input, args.stats, args.output, args.timeout)


if __name__ == "__main__":
    main()
