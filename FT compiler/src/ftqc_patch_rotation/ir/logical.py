"""Logical operation DAG and scheduled logical operations."""
from dataclasses import dataclass
from collections.abc import Iterator
import networkx as nx

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


@dataclass(frozen=True, slots=True)
class ScheduledOperation:
    kind: str
    qubits: tuple[int, ...]
    source_node: int | None = None
