from __future__ import annotations

from .model import PreparedCircuit


def greedy_optimize(circuit: PreparedCircuit) -> tuple[int, ...]:
    """Incrementally flip the qubit incident on most blocked front CZs."""
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

    front_incidence = [
        {epoch: set() for epoch in by_epoch} for by_epoch in incidence
    ]
    for node in front:
        gate = circuit.gate(node)
        for operand, qubit in enumerate(gate.qubits):
            epoch = gate.reset_epochs[operand] if gate.reset_epochs else 0
            front_incidence[qubit][epoch].add(node)

    blocked: set[int] = set()

    def enabled(node: int) -> bool:
        value = initial[node]
        gate = circuit.gate(node)
        for operand, qubit in enumerate(gate.qubits):
            epoch = gate.reset_epochs[operand] if gate.reset_epochs else 0
            value ^= tags[qubit][epoch]
        return value

    def add_blocked(node: int) -> None:
        if node in blocked:
            return
        blocked.add(node)

    def remove_blocked(node: int) -> None:
        if node not in blocked:
            return
        blocked.remove(node)

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
                if indegree[successor] != 0:
                    continue
                front.add(successor)
                successor_gate = circuit.gate(successor)
                for operand, qubit in enumerate(successor_gate.qubits):
                    epoch = (
                        successor_gate.reset_epochs[operand]
                        if successor_gate.reset_epochs
                        else 0
                    )
                    front_incidence[qubit][epoch].add(successor)
                if enabled(successor):
                    queue.append(successor)
                else:
                    add_blocked(successor)
        return executed

    def current_epoch(qubit: int) -> int:
        order = epoch_order[qubit]
        position = epoch_position[qubit]
        while position < len(order) and counts[qubit][order[position]] == 0:
            position += 1
        epoch_position[qubit] = position
        return order[position]

    def cascade_score(qubit: int, epoch: int) -> int:
        """Count the CZ cascade using local deltas without copying base state."""

        def trial_enabled(node: int) -> bool:
            value = enabled(node)
            gate = circuit.gate(node)
            for operand, endpoint in enumerate(gate.qubits):
                endpoint_epoch = (
                    gate.reset_epochs[operand] if gate.reset_epochs else 0
                )
                if endpoint == qubit and endpoint_epoch == epoch:
                    value = not value
            return value

        queue = [
            node
            for node in front_incidence[qubit][epoch]
            if trial_enabled(node)
        ]
        queued = set(queue)
        trial_removed: set[int] = set()
        indegree_delta: dict[int, int] = {}

        while queue:
            node = queue.pop()
            if node in trial_removed or not trial_enabled(node):
                continue
            trial_removed.add(node)

            for successor in circuit.g2.successors(node):
                if successor not in remaining or successor in trial_removed:
                    continue
                new_delta = indegree_delta.get(successor, 0) + 1
                indegree_delta[successor] = new_delta
                if (
                    indegree[successor] - new_delta == 0
                    and successor not in queued
                    and trial_enabled(successor)
                ):
                    queue.append(successor)
                    queued.add(successor)

        return len(trial_removed)

    drain()
    rotations: list[int] = []
    while remaining:
        candidates = {
            qubit
            for node in blocked
            for qubit in circuit.gate(node).qubits
        }
        if not candidates:
            raise RuntimeError("greedy optimizer found no blocked front-layer CZ")

        candidate_scores = {
            qubit: cascade_score(qubit, current_epoch(qubit))
            for qubit in candidates
        }
        qubit = max(candidates, key=lambda q: (candidate_scores[q], -q))
        if candidate_scores[qubit] == 0:
            raise RuntimeError("greedy optimizer found no cascading CZ gain")

        epoch = current_epoch(qubit)
        tags[qubit][epoch] = not tags[qubit][epoch]
        newly_enabled: list[int] = []
        for node in tuple(front_incidence[qubit][epoch]):
            if enabled(node):
                remove_blocked(node)
                newly_enabled.append(node)
            else:
                add_blocked(node)

        rotations.append(qubit)
        if drain(newly_enabled) == 0:
            raise RuntimeError("greedy optimizer failed to enable a front-layer CZ")

    return tuple(rotations)
