"""End-to-end entry point and self-contained JSON artifacts."""
from dataclasses import asdict
import json
from pathlib import Path
import random

import networkx as nx
from qiskit import QuantumCircuit, qasm2

from .compiler import CompiledCircuit, CompiledNode, compile_circuit
from .greedy import greedy_optimize
from .hardware import Processor, ProcessorConfig
from .magic_states import convert_text
from .routing import RoutingError, RoutingSchedule, route_and_schedule, validate_schedule


def compile_processor(circuit, processor, optimizer=greedy_optimize, seed=0, cost_fn=len):
    """Return (compiled logical DAG, spatial schedule, frontend metadata)."""
    metadata = {"seed": seed, "static_trace": True, "magic_state_conversion": None}
    if isinstance(circuit, CompiledCircuit):
        compiled = circuit
    else:
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
        compiled = compile_circuit(circuit, optimizer)
    result = route_and_schedule(compiled, processor, seed=seed, cost_fn=cost_fn)
    return compiled, result, metadata


def save_compilation(path, circuit, processor, schedule, metadata=None):
    report = validate_schedule(circuit, processor, schedule)
    payload = {"schema_version": 1, "processor": processor.to_dict(),
        "circuit": {"num_qubits": circuit.num_qubits, "rotations": list(circuit.rotations),
                    "nodes": [asdict(op) for op in circuit.operations()],
                    "edges": list(circuit.dag.edges)},
        "schedule": schedule.to_dict(), "validation": report, "metadata": metadata or {}}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_compilation(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data["schema_version"] != 1:
        raise ValueError("unsupported compilation schema")
    processor = Processor(ProcessorConfig(**data["processor"]["config"]))
    graph = nx.DiGraph()
    for node in data["circuit"]["nodes"]:
        node["qubits"] = tuple(node["qubits"])
        node["reset_epochs"] = tuple(node.get("reset_epochs", ()))
        operation = CompiledNode(**node)
        graph.add_node(operation.id, operation=operation)
    graph.add_edges_from(data["circuit"]["edges"])
    circuit = CompiledCircuit(data["circuit"]["num_qubits"], graph, tuple(data["circuit"]["rotations"]))
    schedule = RoutingSchedule.from_dict(data["schedule"])
    validate_schedule(circuit, processor, schedule)
    return circuit, processor, schedule, data["metadata"]
