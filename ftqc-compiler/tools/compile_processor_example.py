"""Run the plan's compiler framework and produce replayable artifacts."""
import argparse
import json
from pathlib import Path
import time

from ftqc_patch_rotation.generator import random_layered_clifford_circuit
from ftqc_patch_rotation.hardware import Processor, ProcessorConfig
from ftqc_patch_rotation.hardware_visualize import draw_hardware_schedule
from ftqc_patch_rotation.pipeline import compile_processor, load_compilation, save_compilation
from ftqc_patch_rotation.visualize import draw_compiled_circuit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, default=Path("outputs/framework/random_10x10"))
    parser.add_argument("--seed", type=int, default=20260908)
    parser.add_argument("--no-images", action="store_true")
    args = parser.parse_args()
    config = ProcessorConfig(**json.loads(args.config.read_text(encoding="utf-8"))) if args.config else ProcessorConfig(3,4,5,3,2)
    processor = Processor(config)
    circuit = args.input or random_layered_clifford_circuit(10,10,args.seed)
    start = time.perf_counter()
    compiled, schedule, meta = compile_processor(circuit, processor, seed=args.seed)
    compile_seconds = time.perf_counter()-start
    path = save_compilation(args.output/"compilation.json", compiled, processor, schedule, meta)
    load_compilation(path)
    summary = dict(qubits=compiled.num_qubits, operations=len(compiled.dag),
                   rotations=len(compiled.rotations), cz_blocks=len(schedule.cz_blocks),
                   instruction_blocks=len(schedule.blocks), aod_stages=schedule.stage_count,
                   compile_seconds=compile_seconds, replay_valid=True)
    (args.output/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if not args.no_images:
        draw_compiled_circuit(compiled,args.output/"logical_circuit.png")
        draw_hardware_schedule(processor,schedule,args.output/"stages")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
