from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Iterable, Iterator

import networkx as nx
from qiskit import QuantumCircuit

from .greedy import greedy_optimize
from .model import PreparedCircuit
from .preprocess import preprocess
from .schedule import ScheduledOperation, build_schedule


@dataclass(frozen=True, slots=True)
class CompiledNode:
    """Operation passed to the next compilation layer."""

    id: int
    kind: str
    qubits: tuple[int, ...]
    source_node: int | None = None
    reset_epochs: tuple[int, ...] = ()


@dataclass(slots=True)
class CompiledCircuit:
    """Full operation DAG, including physical auxiliary operations."""

    num_qubits: int
    dag: nx.DiGraph
    rotations: tuple[int, ...]

    def operation(self, node_id: int) -> CompiledNode:
        return self.dag.nodes[node_id]["operation"]

    def operations(self) -> Iterator[CompiledNode]:
        for node_id in nx.lexicographical_topological_sort(self.dag):
            yield self.operation(node_id)


def build_compiled_dag(
    prepared: PreparedCircuit, rotations: Iterable[int]
) -> CompiledCircuit:
    """Materialize the DAG with folding -> icz -> S -> unfolding.

    ``icz`` is an inner-patch CZ operation on one logical patch, not a
    two-logical-qubit CZ.  Its physical operands are left to the next layer.

    Edges are the immediate per-qubit dependencies.  This deliberately
    exposes ``dag`` and typed node metadata as the interface to a future
    lower-level compiler.
    """
    rotation_tuple = tuple(rotations)
    schedule = build_schedule(prepared, rotation_tuple)
    expanded: list[ScheduledOperation] = []
    for operation in schedule:
        if operation.kind == "s":
            expanded.append(
                ScheduledOperation("folding", operation.qubits, operation.source_node)
            )
            expanded.append(
                ScheduledOperation("icz", operation.qubits, operation.source_node)
            )
        expanded.append(operation)
        if operation.kind == "s":
            expanded.append(
                ScheduledOperation("unfolding", operation.qubits, operation.source_node)
            )

    dag = nx.DiGraph()
    frontier: list[int | None] = [None] * prepared.num_qubits
    for node_id, operation in enumerate(expanded):
        node = CompiledNode(
            node_id, operation.kind, operation.qubits, operation.source_node,
            prepared.gate(operation.source_node).reset_epochs if operation.source_node is not None else (),
        )
        dag.add_node(node_id, operation=node)
        predecessors = {
            frontier[qubit]
            for qubit in operation.qubits
            if frontier[qubit] is not None
        }
        dag.add_edges_from((predecessor, node_id) for predecessor in predecessors)
        for qubit in operation.qubits:
            frontier[qubit] = node_id
    return CompiledCircuit(prepared.num_qubits, dag, rotation_tuple)


def compile_circuit(
    circuit: QuantumCircuit,
    optimizer: Callable[[PreparedCircuit], Iterable[int]] = greedy_optimize,
) -> CompiledCircuit:
    """Compile a Qiskit circuit into the next-layer operation DAG."""
    prepared = preprocess(circuit)
    return build_compiled_dag(prepared, optimizer(prepared))
