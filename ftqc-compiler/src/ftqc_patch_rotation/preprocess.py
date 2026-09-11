from __future__ import annotations

from collections.abc import Iterable

import networkx as nx
from qiskit import QuantumCircuit

from .model import GateNode, PreparedCircuit


def _qubit_index(circuit: QuantumCircuit, qubit: object) -> int:
    return circuit.find_bit(qubit).index


def _expanded_operations(
    circuit: QuantumCircuit,
) -> Iterable[tuple[str, tuple[int, ...]]]:
    """Yield operations after replacing CX by H(target)-CZ-H(target)."""
    for instruction in circuit.data:
        name = instruction.operation.name.lower()
        qubits = tuple(_qubit_index(circuit, q) for q in instruction.qubits)
        if name == "cx":
            control, target = qubits
            yield "h", (target,)
            yield "cz", (control, target)
            yield "h", (target,)
        else:
            yield name, qubits


def _project_dag(full: nx.DiGraph, retained: set[int]) -> nx.DiGraph:
    """Project a DAG while preserving reachability through deleted nodes."""
    projected = nx.DiGraph()
    for node in retained:
        projected.add_node(node, **full.nodes[node])
    for source in retained:
        # Walk only through removed operations.  The first retained node on
        # each path is a direct dependency in the projected circuit; stopping
        # there avoids materializing the full transitive closure (quadratic on
        # the large Feynman circuits).
        pending = list(full.successors(source))
        visited: set[int] = set()
        while pending:
            target = pending.pop()
            if target in visited:
                continue
            visited.add(target)
            if target in retained:
                projected.add_edge(source, target)
            else:
                pending.extend(full.successors(target))
    return projected


def preprocess(circuit: QuantumCircuit) -> PreparedCircuit:
    """Build G1 and G2 and annotate CZ nodes with their initial state."""
    g1 = nx.DiGraph()
    g2 = nx.DiGraph()
    g1_frontier: list[set[int]] = [set() for _ in range(circuit.num_qubits)]
    g2_frontier: list[set[int]] = [set() for _ in range(circuit.num_qubits)]
    rotations = [False] * circuit.num_qubits
    reset_epochs = [0] * circuit.num_qubits

    def update_projection(
        graph: nx.DiGraph,
        frontier: list[set[int]],
        node_id: int,
        gate: GateNode,
        retained: bool,
    ) -> None:
        predecessors: set[int] = set()
        for qubit in gate.qubits:
            predecessors.update(frontier[qubit])
        if retained:
            graph.add_node(node_id, gate=gate)
            graph.add_edges_from((pred, node_id) for pred in predecessors)
            new_frontier = {node_id}
        else:
            new_frontier = predecessors
        for qubit in gate.qubits:
            frontier[qubit] = new_frontier.copy()

    for node_id, (kind, qubits) in enumerate(_expanded_operations(circuit)):
        is_executable: bool | None = None
        if kind == "reset":
            # A freshly supplied/reset magic-state register always starts in
            # the canonical patch orientation.
            for qubit in qubits:
                rotations[qubit] = False
                reset_epochs[qubit] += 1
        elif kind == "h":
            rotations[qubits[0]] = not rotations[qubits[0]]
        elif kind == "cz":
            q0, q1 = qubits
            is_executable = rotations[q0] ^ rotations[q1]

        gate = GateNode(
            node_id,
            kind,
            qubits,
            is_executable,
            tuple(reset_epochs[qubit] for qubit in qubits),
        )
        # G1 is also the source for the compiled-circuit output, so retain
        # every operation.  Gates other than H/CZ do not participate in the
        # orientation optimization, but they must remain dependency barriers.
        update_projection(g1, g1_frontier, node_id, gate, True)
        update_projection(g2, g2_frontier, node_id, gate, kind == "cz")
    return PreparedCircuit(circuit.num_qubits, g1, g2)
