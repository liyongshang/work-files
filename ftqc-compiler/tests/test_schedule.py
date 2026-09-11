from qiskit import QuantumCircuit

from ftqc_patch_rotation import preprocess, sat_optimize
from ftqc_patch_rotation.schedule import build_schedule


def test_rotation_does_not_cross_reset_epoch():
    circuit = QuantumCircuit(3)
    circuit.cz(0, 1)
    circuit.reset(0)
    circuit.cz(0, 2)
    schedule = build_schedule(preprocess(circuit), (0, 0))
    assert [op.kind for op in schedule] == ["rot", "cz", "reset", "rot", "cz"]


def test_repeated_resets_replay_orientation():
    from ftqc_patch_rotation import greedy_optimize
    circuit = QuantumCircuit(4)
    for i in range(30):
        circuit.cz(0, 1 + i % 3)
        circuit.reset(0)
    prepared = preprocess(circuit)
    rotations = greedy_optimize(prepared)
    schedule = build_schedule(prepared, rotations)
    state = [False] * 4
    for op in schedule:
        if op.kind in {"h", "rot"}:
            state[op.qubits[0]] ^= True
        elif op.kind == "reset":
            state[op.qubits[0]] = False
        elif op.kind == "cz":
            assert state[op.qubits[0]] != state[op.qubits[1]]
    assert sum(op.kind == "rot" for op in schedule) == len(rotations)


def test_schedule_inserts_rotations_and_preserves_h_gates():
    circuit = QuantumCircuit(2)
    circuit.cz(0, 1)
    circuit.h(0)
    circuit.cz(0, 1)
    prepared = preprocess(circuit)
    rotations = sat_optimize(prepared)

    schedule = build_schedule(prepared, rotations)

    assert [operation.kind for operation in schedule].count("rot") == 2
    assert [operation.kind for operation in schedule].count("h") == 1
    assert [operation.kind for operation in schedule].count("cz") == 2


def test_schedule_retains_reset_as_an_orientation_boundary():
    circuit = QuantumCircuit(3)
    circuit.cz(0, 1)
    circuit.reset(0)
    circuit.cz(0, 2)
    prepared = preprocess(circuit)

    rotations = sat_optimize(prepared)
    schedule = build_schedule(prepared, rotations)

    kinds = [operation.kind for operation in schedule]
    assert kinds.count("reset") == 1
    assert kinds.index("reset") > kinds.index("cz")
    assert kinds.index("reset") < len(kinds) - 1 - kinds[::-1].index("cz")
