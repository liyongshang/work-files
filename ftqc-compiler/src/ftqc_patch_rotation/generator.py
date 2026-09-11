from __future__ import annotations

import numpy as np
from qiskit import QuantumCircuit


def random_clifford_circuit(num_qubits: int, seed: int) -> QuantumCircuit:
    """Generate a random Clifford with CliffordOpt and request CZ entanglers."""
    if num_qubits < 1:
        raise ValueError("num_qubits must be positive")
    try:
        from cliffordopt import (
            paramObj,
            oplist2qiskit,
            str2opList,
            symRand,
            synth_Sp,
        )
    except ImportError as exc:
        raise RuntimeError("CliffordOpt is required for random experiments") from exc

    matrix = symRand(np.random.default_rng(seed), num_qubits)
    params = paramObj()
    params.mode = "Sp"
    params.method = "greedy"
    params.minDepth = False
    params.entanglingGate = "CZ"
    params.hv = 1
    params.hi = 1
    params.ht = 1
    params.hl = 1
    params.wMax = 0
    params.qMax = 10_000
    params.hr = 3

    result = synth_Sp(matrix, params)
    circuit_text = result[5]
    circuit = oplist2qiskit(str2opList(circuit_text), num_qubits)
    if "cz" not in {instruction.operation.name for instruction in circuit.data}:
        raise RuntimeError("CliffordOpt produced no CZ gates; choose another seed")
    return circuit


def random_deep_clifford_circuit(
    num_qubits: int,
    seed: int,
    min_segments: int = 2,
    max_segments: int = 2,
) -> tuple[QuantumCircuit, int]:
    """Concatenate independently generated CliffordOpt circuits (two by default)."""
    if min_segments < 1 or max_segments < min_segments:
        raise ValueError("segment bounds must satisfy 1 <= min_segments <= max_segments")
    rng = np.random.default_rng(seed)
    segment_count = int(rng.integers(min_segments, max_segments + 1))
    combined = QuantumCircuit(num_qubits)
    generated = 0
    candidate = 0
    while generated < segment_count:
        # Separate the experiment seed from per-segment seeds while remaining reproducible.
        segment_seed = seed * 10_000 + candidate
        candidate += 1
        try:
            segment = random_clifford_circuit(num_qubits, segment_seed)
        except RuntimeError:
            continue
        combined.compose(segment, inplace=True)
        generated += 1
    return combined, segment_count


def random_layered_clifford_circuit(
    num_qubits: int, layers: int, seed: int
) -> QuantumCircuit:
    """Generate exact logical layers covering H/S/X/Y/Z/CX/CZ.

    Every qubit receives exactly one operation in each layer, so Qiskit's
    circuit depth equals ``layers``.  The first two layers guarantee complete
    gate-set coverage; later layers are random.
    """
    if num_qubits < 4:
        raise ValueError("num_qubits must be at least 4")
    if layers < 2:
        raise ValueError("layers must be at least 2")
    rng = np.random.default_rng(seed)
    circuit = QuantumCircuit(num_qubits)
    single_gates = ("h", "s", "x", "y", "z")

    for layer in range(layers):
        qubits = list(map(int, rng.permutation(num_qubits)))
        operations: list[tuple[str, tuple[int, ...]]] = []
        if layer == 0:
            operations.extend(
                (single_gates[index % len(single_gates)], (qubit,))
                for index, qubit in enumerate(qubits)
            )
        elif layer == 1:
            operations.extend(
                [("cx", tuple(qubits[:2])), ("cz", tuple(qubits[2:4]))]
            )
            operations.extend(
                (single_gates[int(rng.integers(len(single_gates)))], (qubit,))
                for qubit in qubits[4:]
            )
        else:
            pending = qubits[:]
            while pending:
                if len(pending) >= 2 and rng.random() < 0.45:
                    pair = (pending.pop(), pending.pop())
                    kind = "cx" if rng.random() < 0.5 else "cz"
                    operations.append((kind, pair))
                else:
                    qubit = pending.pop()
                    kind = single_gates[int(rng.integers(len(single_gates)))]
                    operations.append((kind, (qubit,)))
        for kind, operands in operations:
            getattr(circuit, kind)(*operands)
    return circuit
