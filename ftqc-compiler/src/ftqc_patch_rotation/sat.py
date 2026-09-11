from __future__ import annotations

import time

import z3

from .greedy import greedy_optimize
from .model import PreparedCircuit
from .simulator import simulate_rotations


class SatTimeoutError(TimeoutError):
    pass


def _solve_horizon(
    circuit: PreparedCircuit, horizon: int, timeout_ms: int
) -> tuple[int, ...] | None:
    nodes = circuit.cz_nodes
    if not nodes:
        return ()
    solver = z3.Solver()
    solver.set(timeout=max(1, timeout_ms))

    q = {
        (qubit, step): z3.Bool(f"q_{qubit}_{step}")
        for qubit in range(circuit.num_qubits)
        for step in range(1, horizon + 1)
    }
    g = {
        (node, step): z3.Bool(f"g_{node}_{step}")
        for node in nodes
        for step in range(0, horizon + 1)
    }
    e = {
        (node, step): z3.Bool(f"e_{node}_{step}")
        for node in nodes
        for step in range(0, horizon + 1)
    }

    initial = circuit.initial_cz_states()

    def endpoint_epoch(node: int, qubit: int) -> int:
        gate = circuit.gate(node)
        operand = gate.qubits.index(qubit)
        return gate.reset_epochs[operand] if gate.reset_epochs else 0

    earlier_epoch_nodes: dict[tuple[int, int], tuple[int, ...]] = {}
    for node in nodes:
        for qubit in circuit.gate(node).qubits:
            epoch = endpoint_epoch(node, qubit)
            earlier_epoch_nodes[node, qubit] = tuple(
                other
                for other in nodes
                if qubit in circuit.gate(other).qubits
                and endpoint_epoch(other, qubit) < epoch
            )

    for node in nodes:
        solver.add(g[node, 0] == initial[node])
        u, v = circuit.gate(node).qubits
        for step in range(1, horizon + 1):
            # z3py's Xor accepts exactly two Boolean operands; its third positional
            # argument is a context. Nest the XOR so both CZ endpoints participate.
            effects = []
            for qubit in (u, v):
                earlier = earlier_epoch_nodes[node, qubit]
                active = z3.And(
                    [
                        z3.Or([e[old, prior] for prior in range(step)])
                        for old in earlier
                    ]
                )
                effects.append(z3.And(q[qubit, step], active))
            solver.add(
                g[node, step]
                == z3.Xor(z3.Xor(g[node, step - 1], effects[0]), effects[1])
            )

    for step in range(1, horizon + 1):
        solver.add(z3.PbEq([(q[qubit, step], 1) for qubit in range(circuit.num_qubits)], 1))

    for node in nodes:
        solver.add(z3.PbEq([(e[node, step], 1) for step in range(horizon + 1)], 1))
        predecessors = tuple(circuit.g2.predecessors(node))
        for step in range(horizon + 1):
            solver.add(z3.Implies(e[node, step], g[node, step]))
            for predecessor in predecessors:
                solver.add(
                    z3.Implies(
                        e[node, step],
                        z3.Or([e[predecessor, earlier] for earlier in range(step + 1)]),
                    )
                )

    status = solver.check()
    if status == z3.unknown:
        raise SatTimeoutError("Z3 timed out while solving patch rotations")
    if status == z3.unsat:
        return None
    model = solver.model()
    return tuple(
        next(
            qubit
            for qubit in range(circuit.num_qubits)
            if z3.is_true(model.eval(q[qubit, step]))
        )
        for step in range(1, horizon + 1)
    )


def sat_optimize(circuit: PreparedCircuit, timeout_s: float = 60.0) -> tuple[int, ...]:
    """Find a minimum-rotation solution using binary search over a SAT horizon."""
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    initial = simulate_rotations(circuit, ())
    if initial.complete:
        return ()

    bound = greedy_optimize(circuit)
    low, high = 1, len(bound)
    best = bound
    deadline = time.monotonic() + timeout_s
    while low <= high:
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            raise SatTimeoutError("SAT optimization exceeded its total time limit")
        middle = (low + high) // 2
        candidate = _solve_horizon(circuit, middle, remaining_ms)
        if candidate is None:
            low = middle + 1
        else:
            best = candidate
            high = middle - 1

    if not simulate_rotations(circuit, best).complete:
        raise RuntimeError("SAT model produced an invalid rotation sequence")
    return best
