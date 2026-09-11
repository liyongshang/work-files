from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

import networkx as nx

from .model import PreparedCircuit


@dataclass(frozen=True, slots=True)
class ScheduledOperation:
    kind: str
    qubits: tuple[int, ...]
    source_node: int | None = None


def build_schedule(
    circuit: PreparedCircuit, rotations: Iterable[int]
) -> tuple[ScheduledOperation, ...]:
    """Replay G1 and insert patch rotations at blocked front layers."""
    remaining = set(circuit.g1.nodes)
    cz_states = circuit.initial_cz_states()
    schedule: list[ScheduledOperation] = []
    epochs = [0] * circuit.num_qubits

    def drain() -> None:
        while True:
            ready: list[int] = []
            for node in nx.topological_sort(circuit.g1):
                if node not in remaining:
                    continue
                if any(pred in remaining for pred in circuit.g1.predecessors(node)):
                    continue
                gate = circuit.gate(node)
                if gate.kind != "cz" or cz_states[node]:
                    ready.append(node)
            if not ready:
                return
            for node in ready:
                remaining.remove(node)
                gate = circuit.gate(node)
                schedule.append(ScheduledOperation(gate.kind, gate.qubits, node))
                if gate.kind == "reset":
                    for qubit in gate.qubits:
                        epochs[qubit] += 1

    drain()
    for qubit in rotations:
        if not 0 <= qubit < circuit.num_qubits:
            raise ValueError(f"invalid rotation qubit: {qubit}")
        if not remaining:
            break
        schedule.append(ScheduledOperation("rot", (qubit,)))
        for node in remaining:
            gate = circuit.gate(node)
            if gate.kind == "cz" and qubit in gate.qubits:
                operand = gate.qubits.index(qubit)
                epoch = gate.reset_epochs[operand] if gate.reset_epochs else 0
                if epoch == epochs[qubit]:
                    cz_states[node] = not cz_states[node]
        drain()
    if remaining:
        raise ValueError("rotation sequence does not complete G1")
    return tuple(schedule)
