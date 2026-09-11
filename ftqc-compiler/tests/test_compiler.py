import networkx as nx
from qiskit import QuantumCircuit

from ftqc_patch_rotation.compiler import build_compiled_dag
from ftqc_patch_rotation.greedy import greedy_optimize
from ftqc_patch_rotation.preprocess import preprocess


def test_compiled_dag_retains_gates_and_wraps_s():
    circuit = QuantumCircuit(2)
    circuit.x(0)
    circuit.s(0)
    circuit.cz(0, 1)
    circuit.h(1)
    prepared = preprocess(circuit)
    compiled = build_compiled_dag(prepared, greedy_optimize(prepared))
    kinds = [operation.kind for operation in compiled.operations()]

    assert kinds.count("x") == 1
    s_index = kinds.index("s")
    assert kinds[s_index - 2 : s_index + 2] == ["folding", "icz", "s", "unfolding"]
    assert "rot" in kinds
    assert nx.is_directed_acyclic_graph(compiled.dag)


def test_inner_cz_is_a_single_patch_dependency_with_source_provenance():
    circuit = QuantumCircuit(1)
    circuit.s(0)
    prepared = preprocess(circuit)
    compiled = build_compiled_dag(prepared, ())
    operations = list(compiled.operations())
    assert [op.kind for op in operations] == ["folding", "icz", "s", "unfolding"]
    assert all(op.qubits == (0,) and op.source_node == 0 for op in operations)
    assert set(compiled.dag.edges) == {(0, 1), (1, 2), (2, 3)}
    assert compiled.rotations == ()


def test_inner_cz_visualization_preserves_wire_colors(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt
    from ftqc_patch_rotation.visualize import draw_compiled_circuit

    circuit = QuantumCircuit(1)
    circuit.h(0)
    circuit.s(0)
    compiled = build_compiled_dag(preprocess(circuit), ())
    monkeypatch.setattr(plt, "close", lambda *args: None)
    try:
        draw_compiled_circuit(compiled, tmp_path / "inner_cz.png")
        ax = plt.gcf().axes[0]
        assert "iCZ" in [text.get_text() for text in ax.texts]
        assert [line.get_color() for line in ax.lines] == ["#1f77b4"] + ["#d62728"] * 5
    finally:
        monkeypatch.undo()
        plt.close("all")
