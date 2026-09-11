from itertools import product

from qiskit import QuantumCircuit

from ftqc_patch_rotation import (
    greedy_optimize,
    preprocess,
    sat_optimize,
    simulate_rotations,
    trivial_optimize,
    sliding_window_sat_optimize,
)


def _brute_force_optimum(prepared, max_rotations=5):
    for length in range(max_rotations + 1):
        for sequence in product(range(prepared.num_qubits), repeat=length):
            if simulate_rotations(prepared, sequence).complete:
                return sequence
    raise AssertionError("no brute-force solution within bound")


def test_no_rotation_needed_for_aligned_cz():
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cz(0, 1)
    prepared = preprocess(circuit)

    assert greedy_optimize(prepared) == ()
    assert sat_optimize(prepared) == ()


def test_one_flip_enables_dependent_cz_chain():
    circuit = QuantumCircuit(3)
    circuit.cz(0, 1)
    circuit.cz(1, 2)
    prepared = preprocess(circuit)

    greedy = greedy_optimize(prepared)
    optimal = sat_optimize(prepared)

    assert len(greedy) == 1
    assert len(optimal) == 1
    assert simulate_rotations(prepared, optimal).complete


def test_sat_matches_brute_force_when_two_flips_are_required():
    circuit = QuantumCircuit(2)
    circuit.cz(0, 1)
    circuit.h(0)
    circuit.cz(0, 1)
    prepared = preprocess(circuit)

    brute = _brute_force_optimum(prepared)
    optimal = sat_optimize(prepared)

    assert len(brute) == 2
    assert len(optimal) == len(brute)
    assert simulate_rotations(prepared, optimal).complete


def test_sat_matches_brute_force_for_small_mixed_instance():
    circuit = QuantumCircuit(3)
    circuit.h(0)
    circuit.cz(0, 1)
    circuit.h(1)
    circuit.cz(1, 2)
    circuit.cz(0, 2)
    prepared = preprocess(circuit)

    brute = _brute_force_optimum(prepared)
    optimal = sat_optimize(prepared)

    assert len(optimal) == len(brute)
    assert simulate_rotations(prepared, optimal).complete


def test_trivial_is_reproducible_and_completes():
    circuit = QuantumCircuit(3)
    circuit.cz(0, 1)
    circuit.cz(1, 2)
    circuit.h(1)
    circuit.cz(0, 2)
    prepared = preprocess(circuit)

    first = trivial_optimize(prepared, seed=9)
    second = trivial_optimize(prepared, seed=9)

    assert first == second
    assert simulate_rotations(prepared, first).complete


def test_sat_accounts_for_both_cz_endpoints():
    circuit = QuantumCircuit(7)
    circuit.cz(0, 1)
    circuit.cz(0, 2)
    circuit.cz(0, 3)
    circuit.x(1)
    circuit.x(2)
    circuit.x(3)
    circuit.cz(1, 4)
    circuit.cz(2, 5)
    circuit.cz(3, 6)
    prepared = preprocess(circuit)

    optimal = sat_optimize(prepared)

    assert len(optimal) == 3
    assert simulate_rotations(prepared, optimal).complete


def test_sliding_window_sat_matches_full_sat_when_window_contains_all_gates():
    circuit = QuantumCircuit(7)
    circuit.cz(0, 1)
    circuit.cz(0, 2)
    circuit.cz(0, 3)
    circuit.cz(1, 4)
    circuit.cz(2, 5)
    circuit.cz(3, 6)
    prepared = preprocess(circuit)

    full = sat_optimize(prepared)
    windowed = sliding_window_sat_optimize(prepared, window_size=20)

    assert len(windowed) == len(full)
    assert simulate_rotations(prepared, windowed).complete


def test_sliding_window_sat_completes_across_multiple_windows():
    circuit = QuantumCircuit(4)
    for _ in range(4):
        circuit.cz(0, 1)
        circuit.h(0)
        circuit.cz(2, 3)
        circuit.h(2)
    prepared = preprocess(circuit)

    rotations = sliding_window_sat_optimize(prepared, window_size=2)

    assert simulate_rotations(prepared, rotations).complete


def test_greedy_and_sat_do_not_propagate_rot_across_reset():
    circuit = QuantumCircuit(3)
    circuit.cz(0, 1)
    circuit.reset(0)
    circuit.cz(0, 2)
    prepared = preprocess(circuit)

    greedy = greedy_optimize(prepared)
    optimal = sat_optimize(prepared)

    # Without reset semantics, one rotation on q0 would incorrectly enable
    # both CZs. The fresh epoch requires a second rotation.
    assert len(greedy) == 2
    assert len(optimal) == 2
    assert simulate_rotations(prepared, greedy).complete
    assert simulate_rotations(prepared, optimal).complete
