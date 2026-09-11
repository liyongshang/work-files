from pathlib import Path

from qiskit import qasm2

from ftqc_patch_rotation import (
    greedy_optimize,
    preprocess,
    sat_optimize,
    simulate_rotations,
)


BENCHMARK = (
    Path(__file__).parents[1] / "benchmarks" / "feynman_clifford" / "tof_3.qasm"
)


def test_smallest_feynman_circuit_runs_with_greedy_and_z3():
    circuit = qasm2.load(str(BENCHMARK))
    assert circuit.num_qubits == 9
    assert circuit.depth() == 20
    assert circuit.size() == 55

    prepared = preprocess(circuit)
    greedy = greedy_optimize(prepared)
    z3_solution = sat_optimize(prepared, timeout_s=60.0)
    greedy_result = simulate_rotations(prepared, greedy)
    z3_result = simulate_rotations(prepared, z3_solution)

    assert greedy_result.complete
    assert z3_result.complete
    assert len(greedy_result.executed) == len(prepared.cz_nodes) == 15
    assert len(z3_result.executed) == len(prepared.cz_nodes)
    assert len(greedy) == 7
    assert len(z3_solution) == 6
