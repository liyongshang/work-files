import random

from qiskit import qasm2

from tools.convert_feynman_clifford import convert_text


def test_conversion_adds_resources_and_removes_non_clifford_gates():
    source = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[3];
ccx q[0],q[1],q[2];
t q[0];
tdg q[1];
"""
    converted, stats = convert_text(source, random.Random(7))
    circuit = qasm2.loads(converted)

    assert stats == {"ccx": 1, "t": 1, "tdg": 1}
    assert "qreg cczreg[3]; // CCZReg[3]" in converted
    assert "qreg treg[1]; // TReg[1]" in converted
    assert "ccx " not in converted.lower()
    assert all(inst.operation.name not in {"ccx", "t", "tdg"} for inst in circuit.data)
    assert [inst.operation.name for inst in circuit.data].count("reset") == 5


def test_conversion_is_seed_reproducible():
    source = "OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[1];\nt q[0];\n"
    first, _ = convert_text(source, random.Random(11))
    second, _ = convert_text(source, random.Random(11))
    assert first == second
