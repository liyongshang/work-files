import networkx as nx
from qiskit import QuantumCircuit

from ftqc_patch_rotation import preprocess


def test_cx_is_expanded_and_cz_is_initially_executable():
    circuit = QuantumCircuit(2)
    circuit.cx(0, 1)

    prepared = preprocess(circuit)
    kinds = [prepared.gate(node).kind for node in nx.topological_sort(prepared.g1)]

    assert kinds == ["h", "cz", "h"]
    assert len(prepared.cz_nodes) == 1
    assert prepared.gate(prepared.cz_nodes[0]).is_executable is True


def test_g2_preserves_dependency_through_removed_h_gate():
    circuit = QuantumCircuit(2)
    circuit.cz(0, 1)
    circuit.h(0)
    circuit.cz(0, 1)

    prepared = preprocess(circuit)
    first, second = prepared.cz_nodes

    assert prepared.g2.has_edge(first, second)
    assert prepared.gate(first).is_executable is False
    assert prepared.gate(second).is_executable is True


def test_unretained_two_qubit_gate_preserves_cross_qubit_reachability():
    circuit = QuantumCircuit(3)
    circuit.cz(0, 1)
    circuit.swap(1, 2)
    circuit.cz(0, 2)

    prepared = preprocess(circuit)
    first, second = prepared.cz_nodes

    assert prepared.g2.has_edge(first, second)


def test_reset_restores_rot_zero_and_starts_a_new_epoch():
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cz(0, 1)
    circuit.reset(0)
    circuit.cz(0, 1)

    prepared = preprocess(circuit)
    first, second = prepared.cz_nodes
    assert prepared.gate(first).is_executable is True
    assert prepared.gate(second).is_executable is False
    assert prepared.gate(first).reset_epochs[0] == 0
    assert prepared.gate(second).reset_epochs[0] == 1
