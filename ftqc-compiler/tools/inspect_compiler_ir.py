"""README walkthrough: configure, compile, inspect each IR, and draw results."""
from dataclasses import asdict
import json
from pathlib import Path

import networkx as nx
from qiskit import QuantumCircuit, qasm2

from ftqc_patch_rotation import (
    Processor, ProcessorConfig, compile_processor, preprocess,
    save_compilation, load_compilation,
)
from ftqc_patch_rotation.hardware_visualize import draw_hardware_schedule
from ftqc_patch_rotation.visualize import draw_compiled_circuit


def main():
    output = Path(__file__).resolve().parents[1] / "outputs/framework/ir_walkthrough"
    output.mkdir(parents=True, exist_ok=True)
    processor = Processor(ProcessorConfig(
        d=3, a1=4, b1=5, a2=3, b2=2,
        s=5, pair_pitch_x=10, pair_pitch_y=10, pair_offset=1,
        gap_se=10, gap_em=10, L=81, H=180,
    ))

    circuit = QuantumCircuit(3)
    circuit.h(0)
    circuit.t(0)
    circuit.ccz(0, 1, 2)
    circuit.s(1)
    circuit.cx(1, 2)
    circuit.reset(0)
    circuit.cz(0, 2)
    (output / "input.qasm").write_text(qasm2.dumps(circuit), encoding="utf-8")

    compiled, schedule, metadata = compile_processor(circuit, processor, seed=7)
    clifford = qasm2.loads(metadata["static_trace_qasm"])
    (output / "clifford.qasm").write_text(metadata["static_trace_qasm"], encoding="utf-8")

    # Reconstruct the optimizer's internal IR for inspection only.
    prepared = preprocess(clifford)
    for name, graph in (("g1", prepared.g1), ("g2", prepared.g2)):
        payload = {
            "nodes": [asdict(graph.nodes[n]["gate"]) for n in nx.topological_sort(graph)],
            "edges": list(graph.edges),
        }
        (output / f"{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("Input IR:")
    print(circuit.draw(output="text"))
    print("Clifford IR:")
    print(clifford.draw(output="text"))
    print("G1/G2 nodes:", len(prepared.g1), len(prepared.g2))
    print("Rotation sequence:", compiled.rotations)
    print("Compiled DAG nodes:")
    for op in compiled.operations():
        print(asdict(op))
    print("Compiled DAG edges:", list(compiled.dag.edges))
    print("CZ blocks:", schedule.cz_blocks)
    print("Initial mapping:", asdict(schedule.mapping))
    print("Instruction blocks:")
    for index, block in enumerate(schedule.blocks):
        print(index, asdict(block))
    print("Final positions:", schedule.final_positions)

    path = save_compilation(output / "compilation.json", compiled, processor, schedule, metadata)
    _, _, restored, _ = load_compilation(path)
    assert restored.to_dict() == schedule.to_dict()
    draw_compiled_circuit(compiled, output / "logical_circuit.png")
    draw_hardware_schedule(processor, schedule, output / "stages")
    print("Validated AOD stages:", schedule.stage_count)
    print("Output:", output)


if __name__ == "__main__":
    main()
