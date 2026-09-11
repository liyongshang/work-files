from __future__ import annotations

import time

import networkx as nx

from .model import GateNode, PreparedCircuit
from .sat import SatTimeoutError, sat_optimize
from .simulator import drain_executable, flip_qubit


def _window_circuit(
    circuit: PreparedCircuit,
    remaining: set[int],
    states: dict[int, bool],
    window_size: int,
) -> PreparedCircuit:
    remaining_dag = circuit.g2.subgraph(remaining).copy()
    selected: list[int] = []
    for layer in nx.topological_generations(remaining_dag):
        selected.extend(layer)
        if len(selected) > window_size:
            break

    graph = remaining_dag.subgraph(selected).copy()
    for node in graph.nodes:
        old = circuit.gate(node)
        graph.nodes[node]["gate"] = GateNode(
            old.id, old.kind, old.qubits, states[node], old.reset_epochs
        )
    return PreparedCircuit(circuit.num_qubits, graph.copy(), graph)


def sliding_window_sat_optimize(
    circuit: PreparedCircuit,
    window_size: int = 20,
    timeout_s: float = 60.0,
) -> tuple[int, ...]:
    """Repeatedly solve a pure-CZ DAG prefix and apply its first flip."""
    if window_size < 1:
        raise ValueError("window_size must be positive")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")

    deadline = time.monotonic() + timeout_s
    remaining = set(circuit.g2.nodes)
    states = circuit.initial_cz_states()
    rotations: list[int] = []
    drain_executable(circuit, remaining, states)

    while remaining:
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            raise SatTimeoutError(
                "sliding-window SAT exceeded its total circuit time limit"
            )
        window = _window_circuit(circuit, remaining, states, window_size)
        solution = sat_optimize(window, timeout_s=remaining_s)
        if not solution:
            raise RuntimeError("blocked window unexpectedly required no rotation")

        qubit = solution[0]
        flip_qubit(circuit, qubit, remaining, states)
        rotations.append(qubit)
        drain_executable(circuit, remaining, states)

        if time.monotonic() > deadline:
            raise SatTimeoutError(
                "sliding-window SAT exceeded its total circuit time limit"
            )
    return tuple(rotations)
