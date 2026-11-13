"""Initial data and ancilla patch allocation."""
from ftqc_patch_rotation.errors import RoutingError
from ftqc_patch_rotation.ir.routing import Mapping

def initial_mapping(qubits, blocks, circuit, processor):
    qubits = tuple(qubits)
    if len(qubits) > min(len(processor.data_patches), len(processor.ancilla_patches)):
        raise RoutingError("storage capacity insufficient for data and ancilla patches")
    first = dict.fromkeys(qubits, float("inf"))
    for index, block in enumerate(blocks):
        for node in block:
            for q in circuit.operation(node).qubits:
                first[q] = min(first[q], index)
    order = sorted(qubits, key=lambda q: (first[q], q))
    return Mapping(dict(zip(order, processor.data_patches)), dict(zip(order, processor.ancilla_patches)))
