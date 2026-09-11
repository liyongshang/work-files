from __future__ import annotations

import numpy as np

from .model import PreparedCircuit
from .simulator import drain_executable, flip_qubit


def _large_trivial(circuit: PreparedCircuit, rng: np.random.Generator) -> tuple[int, ...]:
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

    def current_epoch(qubit: int) -> int:
        order = epoch_order[qubit]
        position = epoch_position[qubit]
        while position < len(order) and counts[qubit][order[position]] == 0:
            position += 1
        epoch_position[qubit] = position
        return order[position]
    tags = [{epoch: False for epoch in by_epoch} for by_epoch in incidence]
    front_incidence = [
        {epoch: set() for epoch in by_epoch}
        for by_epoch in incidence
    ]
    for node in front:
        gate = circuit.gate(node)
        for operand, qubit in enumerate(gate.qubits):
            epoch = gate.reset_epochs[operand] if gate.reset_epochs else 0
            front_incidence[qubit][epoch].add(node)
    blocked: list[int] = []
    blocked_index: dict[int, int] = {}

    def add_blocked(node: int) -> None:
        if node not in blocked_index:
            blocked_index[node] = len(blocked)
            blocked.append(node)

    def remove_blocked(node: int) -> None:
        index = blocked_index.pop(node, None)
        if index is None:
            return
        last = blocked.pop()
        if index < len(blocked):
            blocked[index] = last
            blocked_index[last] = index

    def enabled(node: int) -> bool:
        value = initial[node]
        gate = circuit.gate(node)
        for operand, qubit in enumerate(gate.qubits):
            epoch = gate.reset_epochs[operand] if gate.reset_epochs else 0
            value ^= tags[qubit][epoch]
        return value

    def drain(queue: list[int] | None = None) -> int:
        if queue is None:
            queue = []
            for node in front:
                if enabled(node):
                    queue.append(node)
                else:
                    add_blocked(node)
        executed = 0
        while queue:
            node = queue.pop()
            if node not in remaining or node not in front or not enabled(node):
                continue
            remaining.remove(node)
            front.remove(node)
            remove_blocked(node)
            executed += 1
            gate = circuit.gate(node)
            for operand, qubit in enumerate(gate.qubits):
                epoch = gate.reset_epochs[operand] if gate.reset_epochs else 0
                counts[qubit][epoch] -= 1
                front_incidence[qubit][epoch].discard(node)
            for successor in circuit.g2.successors(node):
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    front.add(successor)
                    successor_gate = circuit.gate(successor)
                    for operand, endpoint in enumerate(successor_gate.qubits):
                        successor_epoch = (
                            successor_gate.reset_epochs[operand]
                            if successor_gate.reset_epochs
                            else 0
                        )
                        front_incidence[endpoint][successor_epoch].add(successor)
                    if enabled(successor):
                        queue.append(successor)
                    else:
                        add_blocked(successor)
        return executed

    drain()
    rotations: list[int] = []
    while remaining:
        if not blocked:
            raise RuntimeError("no blocked front-layer CZ is available")
        node = blocked[int(rng.integers(len(blocked)))]
        endpoints = circuit.gate(node).qubits
        qubit = endpoints[int(rng.integers(2))]
        epoch = current_epoch(qubit)
        tags[qubit][epoch] = not tags[qubit][epoch]
        newly_enabled: list[int] = []
        for affected in tuple(front_incidence[qubit][epoch]):
            if enabled(affected):
                remove_blocked(affected)
                newly_enabled.append(affected)
            else:
                add_blocked(affected)
        rotations.append(qubit)
        if drain(newly_enabled) == 0:
            raise RuntimeError("trivial optimizer failed to make progress")
    return tuple(rotations)


def trivial_optimize(circuit: PreparedCircuit, seed: int | None = None) -> tuple[int, ...]:
    """Randomly flip one endpoint of a blocked front-layer CZ gate."""
    rng = np.random.default_rng(seed)
    if len(circuit.cz_nodes) > 500:
        return _large_trivial(circuit, rng)
    remaining = set(circuit.g2.nodes)
    states = circuit.initial_cz_states()
    drain_executable(circuit, remaining, states)
    rotations: list[int] = []

    while remaining:
        blocked_front = [
            node
            for node in circuit.cz_nodes
            if node in remaining
            and not states[node]
            and all(pred not in remaining for pred in circuit.g2.predecessors(node))
        ]
        if not blocked_front:
            raise RuntimeError("no blocked front-layer CZ is available")
        node = blocked_front[int(rng.integers(len(blocked_front)))]
        endpoints = circuit.gate(node).qubits
        qubit = endpoints[int(rng.integers(2))]
        flip_qubit(circuit, qubit, remaining, states)
        rotations.append(qubit)
        progressed = drain_executable(circuit, remaining, states)
        if not progressed:
            raise RuntimeError("trivial optimizer failed to make progress")
    return tuple(rotations)
