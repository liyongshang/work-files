"""Materialize rotations and S deformation into the complete logical DAG."""
from collections.abc import Callable, Iterable
import networkx as nx
from qiskit import QuantumCircuit
from ftqc_patch_rotation.ir.logical import CompiledCircuit, CompiledNode, ScheduledOperation
from ftqc_patch_rotation.ir.rotation import PreparedCircuit
from ftqc_patch_rotation.passes.patch_rotation.greedy import greedy_optimize
from ftqc_patch_rotation.passes.patch_rotation.preprocess import preprocess
from ftqc_patch_rotation.passes.patch_rotation.schedule import build_schedule

def build_compiled_dag(
    prepared: PreparedCircuit, rotations: Iterable[int], *, expand_legacy_s: bool = True
) -> CompiledCircuit:
    """Materialize the DAG with folding -> icz -> S -> unfolding.

    ``icz`` is an inner-patch CZ operation on one logical patch, not a
    two-logical-qubit CZ.  Its physical operands are left to the next layer.

    Edges are the immediate per-qubit dependencies.  This deliberately
    exposes ``dag`` and typed node metadata as the interface to a future
    lower-level compiler.
    """
    if not isinstance(expand_legacy_s, bool):
        raise ValueError("expand_legacy_s must be a bool")
    rotation_tuple = tuple(rotations)
    schedule = build_schedule(prepared, rotation_tuple)
    expanded: list[ScheduledOperation] = []
    for operation in schedule:
        if operation.kind == "s" and expand_legacy_s:
            expanded.append(
                ScheduledOperation("folding", operation.qubits, operation.source_node)
            )
            expanded.append(
                ScheduledOperation("icz", operation.qubits, operation.source_node)
            )
        expanded.append(operation)
        if operation.kind == "s" and expand_legacy_s:
            expanded.append(
                ScheduledOperation("unfolding", operation.qubits, operation.source_node)
            )

    dag = nx.DiGraph()
    frontier: list[int | None] = [None] * prepared.num_qubits
    for node_id, operation in enumerate(expanded):
        node = CompiledNode(
            node_id, operation.kind, operation.qubits, operation.source_node,
            prepared.gate(operation.source_node).reset_epochs if operation.source_node is not None else (),
        )
        dag.add_node(node_id, operation=node)
        predecessors = {
            frontier[qubit]
            for qubit in operation.qubits
            if frontier[qubit] is not None
        }
        dag.add_edges_from((predecessor, node_id) for predecessor in predecessors)
        for qubit in operation.qubits:
            frontier[qubit] = node_id
    return CompiledCircuit(prepared.num_qubits, dag, rotation_tuple)


def compile_circuit(
    circuit: QuantumCircuit,
    optimizer: Callable[[PreparedCircuit], Iterable[int]] = greedy_optimize,
) -> CompiledCircuit:
    """Compile a Qiskit circuit into the next-layer operation DAG."""
    prepared = preprocess(circuit)
    return build_compiled_dag(prepared, optimizer(prepared))


def compile_rotated_circuit(
    circuit: QuantumCircuit,
    optimizer: Callable[[PreparedCircuit], Iterable[int]] = greedy_optimize,
    *, allow_resource_ops: bool = False,
) -> CompiledCircuit:
    """Rotated-code Clifford DAG; S/Sdg remain atomic mid-cycle SE gates.

    ROT choices use the existing ZX pairing optimizer. Physical gate circuits
    and SE readout context are supplied by subsequent code-specific passes.
    """
    supported = {"h", "cx", "cz", "rot", "s", "sdg", "x", "y", "z", "id", "barrier"}
    if allow_resource_ops:
        supported |= {"prepare_t", "measure_t0", "measure_t1"}
    for instruction in circuit.data:
        if instruction.operation.name not in supported:
            raise ValueError(f"unsupported rotated-code gate: {instruction.operation.name}")
        if getattr(instruction.operation, "condition", None) is not None:
            raise ValueError("conditional rotated-code gates are not supported")
    prepared = preprocess(circuit)
    return build_compiled_dag(prepared, optimizer(prepared), expand_legacy_s=False)
