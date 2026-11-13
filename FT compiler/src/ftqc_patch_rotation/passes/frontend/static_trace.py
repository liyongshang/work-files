"""Normalize QASM/QuantumCircuit inputs into a reproducible static trace."""
from pathlib import Path
import random
from qiskit import QuantumCircuit, qasm2
from ftqc_patch_rotation.errors import RoutingError
from .magic_states import convert_text


def prepare_static_trace(circuit, seed=0):
    """Return the normalized circuit and frontend provenance metadata."""
    metadata = {"seed": seed, "static_trace": True, "magic_state_conversion": None}
    if isinstance(circuit, (str, Path)):
        source = Path(circuit).read_text(encoding="utf-8")
        metadata["input_qasm"] = source
        circuit = qasm2.loads(source)
    for inst in circuit.data:
        if getattr(inst.operation, "condition", None) is not None or inst.operation.name in {"if_else", "while_loop", "for_loop", "switch_case"}:
            raise RoutingError("dynamic classical control is not supported by the static frontend")
    names = {inst.operation.name for inst in circuit.data}
    if names & {"t", "tdg", "ccx", "ccz"}:
        normalized = QuantumCircuit(*circuit.qregs, *circuit.cregs)
        for inst in circuit.data:
            if inst.operation.name == "ccz":
                a, b, c = inst.qubits
                normalized.h(c)
                normalized.ccx(a, b, c)
                normalized.h(c)
            else:
                normalized.append(inst.operation, inst.qubits, inst.clbits)
        if any(reg.name in {"treg", "cczreg", "tmeas", "cczmeas"} for reg in [*normalized.qregs, *normalized.cregs]):
            raise RoutingError("reserved magic-state register names already exist")
        text, stats = convert_text(qasm2.dumps(normalized), random.Random(seed))
        metadata["magic_state_conversion"] = stats
        metadata["converted_qasm"] = text
        circuit = qasm2.loads(text)
    metadata["static_trace_qasm"] = qasm2.dumps(circuit)
    metadata["qubit_registers"] = [
        {"qubit": circuit.find_bit(q).index,
         "registers": [[reg.name, index] for reg, index in circuit.find_bit(q).registers]}
        for q in circuit.qubits]
    return circuit, metadata
