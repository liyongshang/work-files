from unittest.mock import patch

from qiskit import QuantumCircuit

from ftqc_patch_rotation.generator import (
    random_deep_clifford_circuit,
    random_layered_clifford_circuit,
)


def _segment(num_qubits, seed):
    circuit = QuantumCircuit(num_qubits)
    circuit.h(seed % num_qubits)
    circuit.cz(0, 1)
    return circuit


@patch("ftqc_patch_rotation.generator.random_clifford_circuit", side_effect=_segment)
def test_deep_generator_concatenates_two_segments_by_default(mock_generator):
    circuit, segments = random_deep_clifford_circuit(4, seed=7)

    assert segments == 2
    assert mock_generator.call_count == segments
    assert len(circuit.data) == 2 * segments


def test_layered_generator_has_exact_depth_and_full_gate_set():
    circuit = random_layered_clifford_circuit(10, 10, seed=12)
    kinds = {instruction.operation.name for instruction in circuit.data}

    assert circuit.depth() == 10
    assert {"h", "s", "x", "y", "z", "cx", "cz"} <= kinds
