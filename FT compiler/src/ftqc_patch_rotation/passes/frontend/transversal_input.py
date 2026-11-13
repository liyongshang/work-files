"""Clifford+T static trace under one infinitely replenishable encoded T resource."""
import random

from qiskit import QuantumCircuit
from qiskit.circuit import Gate
from .magic_states import t_injection_steps


def prepare_transversal_input(circuit, *, seed=0, t_measurements=None):
    count = sum(i.operation.name in {"t", "tdg"} for i in circuit.data)
    if not count:
        if t_measurements is not None and tuple(t_measurements):
            raise ValueError("measurement branches provided without T gates")
        return circuit, {}
    rng = random.Random(seed)
    bits = tuple(rng.randrange(2) for _ in range(count)) if t_measurements is None else tuple(t_measurements)
    if len(bits) != count or any(type(b) is not int or b not in (0, 1) for b in bits):
        raise ValueError("provide exactly one 0/1 measurement branch per T/Tdg")
    resource = circuit.num_qubits
    result = QuantumCircuit(resource+1)
    result.global_phase = circuit.global_phase
    result.append(Gate("prepare_t", 1, []), [resource])
    injection_index = 0
    injections = []
    for instruction in circuit.data:
        operation = instruction.operation
        if instruction.clbits or getattr(operation, "condition", None) is not None:
            raise ValueError("dynamic/classical inputs are not supported in the static T model")
        operands = tuple(circuit.find_bit(q).index for q in instruction.qubits)
        if operation.name not in {"t", "tdg"}:
            result.append(operation, operands)
            continue
        q, = operands
        bit = bits[injection_index]
        injections.append({"index": injection_index, "gate": operation.name, "data_qubit": q,
                           "resource_qubit": resource, "assumed_measurement": bit})
        for kind, targets in t_injection_steps(q, resource, bit, operation.name == "tdg"):
            if kind == "measure":
                result.append(Gate(f"measure_t{bit}", 1, []), targets)
                # Preserve the readout -> feedforward dependency even though
                # the branch is fixed instead of dynamically executed.
                result.barrier(q, resource)
            elif kind == "reset":
                result.append(Gate("prepare_t", 1, []), targets)
            else:
                getattr(result, kind)(*targets)
        injection_index += 1
    return result, {"model": "reusable-encoded-T-static-branch-v1", "algorithm_qubits": circuit.num_qubits,
                    "resource_qubits": [resource], "injections": injections,
                    "assumptions": ["prepare_t supplies a fresh encoded |T> after every use",
                                    "no distillation or resource factory is modeled",
                                    "logical Z readout is an abstract macro",
                                    "measurement branches are fixed; dynamic feedback is not implemented"],
                    "seed": seed}
