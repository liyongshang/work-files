from __future__ import annotations

import argparse
import json
from pathlib import Path

import networkx as nx
from qiskit import qasm2

from ftqc_patch_rotation.compiler import compile_circuit
from ftqc_patch_rotation.generator import random_layered_clifford_circuit
from ftqc_patch_rotation.visualize import draw_compiled_circuit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("outputs/compiled_clifford_10x10"))
    parser.add_argument("--seed", type=int, default=20260901)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    source = random_layered_clifford_circuit(10, 10, args.seed)
    (args.output / "input_circuit.qasm").write_text(
        qasm2.dumps(source), encoding="utf-8"
    )
    compiled = compile_circuit(source)
    image = draw_compiled_circuit(
        compiled,
        args.output / "compiled_circuit.png",
        title="10-qubit, 10-layer random Clifford circuit (compiled)",
    )
    nodes = [
        {
            "id": operation.id,
            "kind": operation.kind,
            "qubits": list(operation.qubits),
            "source_node": operation.source_node,
        }
        for operation in compiled.operations()
    ]
    payload = {
        "num_qubits": compiled.num_qubits,
        "input_depth": source.depth(),
        "rotations": list(compiled.rotations),
        "nodes": nodes,
        "edges": [list(edge) for edge in compiled.dag.edges],
    }
    (args.output / "compiled_dag.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    assert nx.is_directed_acyclic_graph(compiled.dag)
    print(image)


if __name__ == "__main__":
    main()
