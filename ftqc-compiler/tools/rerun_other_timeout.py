"""Rerun trivial and greedy on prior non-SAT-completed Feynman circuits."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import matplotlib.pyplot as plt
from qiskit import qasm2

from ftqc_patch_rotation import (
    greedy_optimize,
    preprocess,
    simulate_rotations,
    trivial_optimize,
)


ROOT = Path(__file__).parents[1]
INPUT = ROOT / "benchmarks" / "feynman_clifford"
PRIOR = ROOT / "results_feynman_algorithms" / "results.json"
OUTPUT = ROOT / "results_other_timeout_rerun"


def draw(rows: list[dict], output: Path) -> None:
    x = list(range(len(rows)))
    fig, ax = plt.subplots(figsize=(max(14, len(rows) * 0.7), 6.5))
    percentages = [
        100.0 * row["greedy_rotations"] / row["trivial_rotations"]
        for row in rows
    ]
    bars = ax.bar(x, percentages, width=0.72, color="#2F75B5")
    ax.axhline(100.0, color="#C00000", linestyle="--", linewidth=1.5,
               label="Trivial baseline (100%)")
    ax.set_ylabel("Greedy / Trivial rotations (%)")
    ax.set_ylim(0, max(105.0, max(percentages) * 1.12))
    ax.set_xticks(
        x,
        [Path(row["circuit"]).stem for row in rows],
        rotation=55,
        ha="right",
    )
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    for bar, value in zip(bars, percentages):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.0,
            f"{value:.1f}%",
            ha="center",
            va="bottom",
            fontsize=7,
            rotation=90,
        )
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    samples = [row for row in prior if row["sat_status"] != "completed"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    checkpoint = OUTPUT / "results.json"
    rows = (
        json.loads(checkpoint.read_text(encoding="utf-8"))
        if checkpoint.exists()
        else []
    )
    done = {row["circuit"] for row in rows}

    for index, old in enumerate(samples, start=1):
        name = old["circuit"]
        if name in done:
            print(f"[{index}/{len(samples)}] {name}: resumed", flush=True)
            continue

        circuit = qasm2.load(str(INPUT / name))
        started = time.perf_counter()
        prepared = preprocess(circuit)
        preprocess_s = time.perf_counter() - started

        started = time.perf_counter()
        trivial = trivial_optimize(prepared, seed=20260826 + index)
        trivial_s = time.perf_counter() - started

        started = time.perf_counter()
        greedy = greedy_optimize(prepared)
        greedy_s = time.perf_counter() - started

        if not simulate_rotations(prepared, trivial).complete:
            raise RuntimeError(f"trivial incomplete for {name}")
        if not simulate_rotations(prepared, greedy).complete:
            raise RuntimeError(f"greedy incomplete for {name}")

        row = {
            "circuit": name,
            "prior_sat_status": old["sat_status"],
            "data_qubits": old["data_qubits"],
            "total_qubits": old["total_qubits"],
            "depth": old["depth"],
            "gate_count": old["gate_count"],
            "cz_nodes": len(prepared.cz_nodes),
            "trivial_rotations": len(trivial),
            "greedy_rotations": len(greedy),
            "trivial_time_s": trivial_s,
            "greedy_time_s": greedy_s,
            "preprocess_time_s": preprocess_s,
        }
        rows.append(row)
        checkpoint.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(
            f"[{index}/{len(samples)}] {name}: "
            f"trivial={len(trivial)} rot/{trivial_s:.4f}s, "
            f"greedy={len(greedy)} rot/{greedy_s:.4f}s, "
            f"preprocess={preprocess_s:.4f}s",
            flush=True,
        )

    with (OUTPUT / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    draw(rows, OUTPUT / "rotation_comparison.png")


if __name__ == "__main__":
    main()
