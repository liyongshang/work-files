"""Shared operation semantics and resource constraints for planning and replay."""
import networkx as nx
from ftqc_patch_rotation.errors import RoutingError

CZ = {"cz", "icz"}
DEFORMATION = {"rot", "folding", "unfolding"}
SUPPORTED = CZ | DEFORMATION | {"h", "s", "sdg", "x", "y", "z", "id", "reset", "measure", "barrier",
                               "prepare_t", "measure_t0", "measure_t1"}

def _check_input(circuit):
    if not nx.is_directed_acyclic_graph(circuit.dag):
        raise RoutingError("input operation graph is not a DAG")
    for op in circuit.operations():
        if op.kind not in SUPPORTED:
            raise RoutingError(f"unsupported operation {op.kind} at node {op.id}")
        if len(set(op.qubits)) != len(op.qubits) or any(q < 0 or q >= circuit.num_qubits for q in op.qubits):
            raise RoutingError(f"invalid operands at node {op.id}")
        arity = 2 if op.kind == "cz" else 1
        if op.kind != "barrier" and len(op.qubits) != arity:
            raise RoutingError(f"invalid arity at node {op.id}")


def _update_state(op, orientations, epochs):
    if op.kind in {"rot", "h"}:
        orientations[op.qubits[0]] ^= True
    elif op.kind in {"reset", "prepare_t"}:
        orientations[op.qubits[0]] = False
        epochs[op.qubits[0]] += 1


def _check_gate_group(group, circuit, pos, processor, orientations):
    active, pairs = set(), set()
    for n in group:
        op = circuit.operation(n)
        if active.intersection(op.qubits):
            raise RoutingError("gate group shares logical qubits")
        active.update(op.qubits)
        pair = processor.pair_of(pos[op.qubits[0]])
        if pair is None or pair in pairs:
            raise RoutingError(f"invalid or shared pair at node {n}")
        pairs.add(pair)
        occupants = {q for q, p in pos.items() if processor.pair_of(p) == pair}
        if occupants != set(op.qubits):
            raise RoutingError(f"incorrect pair occupants at node {n}: {occupants}")
        if op.kind == "cz" and orientations[op.qubits[0]] == orientations[op.qubits[1]]:
            raise RoutingError(f"CZ orientation mismatch at node {n}")
    if any(processor.zone_of(p) != "storage" for q, p in pos.items() if q not in active):
        raise RoutingError("inactive data block outside storage")


def _check_mapping(mapping, circuit, processor):
    for positions, allowed in ((mapping.initial_data_patch, processor.data_patches),
                               (mapping.ancilla_patch, processor.ancilla_patches)):
        if set(positions) != set(range(circuit.num_qubits)) or len(set(positions.values())) != circuit.num_qubits:
            raise RoutingError("mapping must cover every qubit injectively")
        if not set(positions.values()) <= set(allowed):
            raise RoutingError("mapping outside designated storage region")
    if processor.config.code_kind == "rotated_surface" and mapping.initial_data_patch != mapping.ancilla_patch:
        raise RoutingError("rotated data/check blocks must share their storage home")
