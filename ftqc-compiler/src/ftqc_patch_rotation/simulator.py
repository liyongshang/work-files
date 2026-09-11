from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

import networkx as nx

from .model import PreparedCircuit


@dataclass(frozen=True, slots=True)
class SimulationResult:
    rotations: tuple[int, ...]
    executed: tuple[int, ...]
    complete: bool


def drain_executable(
    circuit: PreparedCircuit,
    remaining: set[int],
    states: dict[int, bool],
) -> list[int]:
    """Execute all currently enabled front-layer CZ gates."""
    executed: list[int] = []
    # One topological pass is sufficient: every predecessor is visited before
    # its successors, so executing a node immediately exposes later nodes in
    # the same pass. A blocked front node stays blocked until the next flip.
    for node in circuit.cz_nodes:
        if (
            node in remaining
            and states[node]
            and all(pred not in remaining for pred in circuit.g2.predecessors(node))
        ):
            remaining.remove(node)
            executed.append(node)
    return executed


def flip_qubit(
    circuit: PreparedCircuit,
    qubit: int,
    remaining: set[int],
    states: dict[int, bool],
) -> None:
    if qubit < 0 or qubit >= circuit.num_qubits:
        raise ValueError(f"qubit {qubit} is outside [0, {circuit.num_qubits})")
    affected: list[tuple[int, int]] = []
    for node in remaining:
        gate = circuit.gate(node)
        for operand, endpoint in enumerate(gate.qubits):
            if endpoint == qubit:
                epoch = gate.reset_epochs[operand] if gate.reset_epochs else 0
                affected.append((node, epoch))
    if not affected:
        return

    # Gates after the next reset belong to a fresh resource state and must not
    # inherit this rotation. Non-reset data qubits have just epoch zero.
    current_epoch = min(epoch for _, epoch in affected)
    for node, epoch in affected:
        if epoch == current_epoch:
            states[node] = not states[node]


def simulate_rotations(
    circuit: PreparedCircuit, rotations: Iterable[int]
) -> SimulationResult:
    nodes = circuit.cz_nodes
    remaining = set(nodes)
    initial = circuit.initial_cz_states()
    indegree = {node: circuit.g2.in_degree(node) for node in nodes}
    front = {node for node in nodes if indegree[node] == 0}
    incidence: list[dict[int, set[int]]] = [
        {} for _ in range(circuit.num_qubits)
    ]
    for node in nodes:
        gate = circuit.gate(node)
        for operand, qubit in enumerate(gate.qubits):
            epoch = gate.reset_epochs[operand] if gate.reset_epochs else 0
            incidence[qubit].setdefault(epoch, set()).add(node)
    counts = [
        {epoch: len(epoch_nodes) for epoch, epoch_nodes in by_epoch.items()}
        for by_epoch in incidence
    ]
    epoch_order = [sorted(by_epoch) for by_epoch in counts]
    epoch_position = [0] * circuit.num_qubits
    tags = [{epoch: False for epoch in by_epoch} for by_epoch in incidence]

    def enabled(node: int) -> bool:
        value = initial[node]
        gate = circuit.gate(node)
        for operand, qubit in enumerate(gate.qubits):
            epoch = gate.reset_epochs[operand] if gate.reset_epochs else 0
            value ^= tags[qubit][epoch]
        return value

    def drain() -> list[int]:
        queue = [node for node in front if enabled(node)]
        drained: list[int] = []
        while queue:
            node = queue.pop()
            if node not in remaining or node not in front or not enabled(node):
                continue
            remaining.remove(node)
            front.remove(node)
            drained.append(node)
            gate = circuit.gate(node)
            for operand, qubit in enumerate(gate.qubits):
                epoch = gate.reset_epochs[operand] if gate.reset_epochs else 0
                counts[qubit][epoch] -= 1
            for successor in circuit.g2.successors(node):
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    front.add(successor)
                    if enabled(successor):
                        queue.append(successor)
        return drained

    executed = drain()
    used: list[int] = []
    for qubit in rotations:
        if not remaining:
            break
        if qubit < 0 or qubit >= circuit.num_qubits:
            raise ValueError(f"qubit {qubit} is outside [0, {circuit.num_qubits})")
        order = epoch_order[qubit]
        position = epoch_position[qubit]
        while position < len(order) and counts[qubit][order[position]] == 0:
            position += 1
        epoch_position[qubit] = position
        if position < len(order):
            epoch = order[position]
            tags[qubit][epoch] = not tags[qubit][epoch]
        used.append(qubit)
        executed.extend(drain())
    return SimulationResult(tuple(used), tuple(executed), not remaining)
