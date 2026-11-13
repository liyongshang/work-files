"""Inspect the pinned SE checkout without modifying it or the compiler pipeline."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/se_repository_review"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / "external/quantum-compiler/Quantum-compiler"
    if not (source / "se_circuits.py").is_file():
        parser.error("clone the SE repository into external/quantum-compiler first")
    sys.path.insert(0, str(source))
    import stim
    from se_circuits import SCHEMES, build_se_circuit
    from convert_circuit import cnot_to_cz_layered_with_cnot_batches, assert_conflict_free
    from add_si_noise import SINoiseParams, add_si_noise_to_circuit
    from atom_loss import apply_atom_loss

    args.output.mkdir(parents=True, exist_ok=True)
    reports = []
    for distance, rounds in ((3, 2), (5, 3)):
        for scheme in SCHEMES:
            program = build_se_circuit(scheme, distance, rounds, final_measure=False)
            converted = cnot_to_cz_layered_with_cnot_batches(program.circuit)
            assert_conflict_free(converted)
            noisy = add_si_noise_to_circuit(
                converted, SINoiseParams(.001, .002, .0001, .001, .001))
            lossy, log = apply_atom_loss(noisy, .01, seed=1, schedule=program)
            samples = lossy.compile_sampler(seed=1).sample(16)
            assert samples.shape == (16, lossy.num_measurements)
            assert converted.num_measurements == program.circuit.num_measurements
            assert lossy.num_measurements == program.circuit.num_measurements
            # Count occupancy from reset-generation / destructive-readout events,
            # not from the largest allocated Stim wire number.
            alive, peak = set(), 0
            for event in program.events:
                if event["kind"] == "reset":
                    alive.add(event["wire"])
                elif event["kind"] == "SSR":
                    alive.discard(event["wire"])
                peak = max(peak, len(alive))
            feedback = sum(1 for op in converted.flattened()
                           if op.name in {"CX", "CZ"}
                           and any(t.is_measurement_record_target for t in op.targets_copy()))
            report = {
                "scheme": scheme, "distance": distance, "rounds": rounds,
                "final_measure": False, "allocated_stim_wires": program.circuit.num_qubits,
                "peak_live_wires": peak, "logical_data_wires": len(program.final_data),
                "measurements": program.circuit.num_measurements,
                "detectors": program.circuit.num_detectors,
                "prep_rounds": program.prep_rounds,
                "feedback_instructions_after_cz_conversion": feedback,
                "ideal_initialization_steps": sum(s["stage"] == "ideal_init" for s in program.steps.values()),
                "shuttle_events": sum(e["kind"] == "shuttle" for e in program.events),
                "final_data_same_wires_as_initial": program.final_data == program.initial_data,
                "initial_data": program.initial_data, "final_data": program.final_data,
                "stage_names": sorted({s["stage"] for s in program.steps.values()}),
                "loss_event_summary": dict(Counter(e["event"] for e in log)),
                "samples": list(samples.shape),
            }
            reports.append(report)
            prefix = args.output / f"{scheme}_d{distance}_r{rounds}"
            prefix.with_suffix(".stim").write_text(str(converted), encoding="utf-8")
            metadata = {k: v for k, v in vars(program).items() if k != "circuit"}
            prefix.with_suffix(".schedule.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            print(f"{scheme:16} d={distance} r={rounds}: allocated={report['allocated_stim_wires']} "
                  f"peak_live={peak} data={len(program.final_data)} feedback={feedback}")
    (args.output / "inspection.json").write_text(
        json.dumps({"stim_version": stim.__version__, "cases": reports}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
