from __future__ import annotations

from dataclasses import dataclass

import networkx as nx


@dataclass(frozen=True, slots=True)
class GateNode:
    """A retained logical operation in the preprocessed circuit."""

    id: int
    kind: str
    qubits: tuple[int, ...]
    is_executable: bool | None = None
    # Reset epoch for each operand.  A patch rotation may affect only the
    # current epoch of a repeatedly reset resource qubit.
    reset_epochs: tuple[int, ...] = ()


@dataclass(slots=True)
class PreparedCircuit:
    """The G1/G2 DAGs defined in plan.txt."""

    num_qubits: int
    g1: nx.DiGraph
    g2: nx.DiGraph

    @property
    def cz_nodes(self) -> tuple[int, ...]:
        return tuple(nx.topological_sort(self.g2))

    def gate(self, node_id: int) -> GateNode:
        return self.g1.nodes[node_id]["gate"]

    def initial_cz_states(self) -> dict[int, bool]:
        return {
            node: bool(self.g2.nodes[node]["gate"].is_executable)
            for node in self.g2.nodes
        }
