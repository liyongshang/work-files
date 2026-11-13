"""Versioned compilation artifacts; save and load both replay validation."""
from dataclasses import asdict
import json
import re
from pathlib import Path
import networkx as nx
from ftqc_patch_rotation.ir.logical import CompiledCircuit, CompiledNode
from ftqc_patch_rotation.ir.routing import RoutingSchedule
from ftqc_patch_rotation.hardware import Processor, ProcessorConfig
from ftqc_patch_rotation.passes.routing.validation import validate_schedule

def renumber_bus_output(value, rows):
    """Mirror lower SLM identifiers at the output boundary (an involution).

    Internal physical IDs stay compatible with historical artifacts. Public
    lower IDs count from the entanglement-facing edge, as upper IDs already do.
    """
    if isinstance(value, str):
        return re.sub(r"\bstorage:(\d+):(\d+)\b",
                      lambda m: f"storage:{rows-1-int(m[1])}:{m[2]}", value)
    if isinstance(value, dict):
        return {renumber_bus_output(k, rows): renumber_bus_output(v, rows) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [renumber_bus_output(v, rows) for v in value]
    return value


def _renumber_compilation(payload):
    result = renumber_bus_output(payload, payload["processor"]["config"]["a1"])
    rows = payload["processor"]["config"]["a1"]
    for patch in result["processor"]["patches"]:
        if patch["zone"] == "storage":
            patch["row"] = rows-1-patch["row"]
    result["program"]["transport_topology"]["numbering"]["physical_patch_ids"] = (
        "preserved from Processor" if payload.get("patch_id_numbering") == "bus-facing-rows"
        else "SLM patch IDs use bus-facing row numbers")
    return result


def compiled_circuit_to_dict(circuit):
    return {"num_qubits": circuit.num_qubits, "rotations": list(circuit.rotations),
            "nodes": [asdict(op) for op in circuit.operations()], "edges": list(circuit.dag.edges)}


def compiled_circuit_from_dict(value):
    graph = nx.DiGraph()
    for saved in value["nodes"]:
        node = {**saved, "qubits": tuple(saved["qubits"]), "reset_epochs": tuple(saved.get("reset_epochs", ()))}
        operation = CompiledNode(**node)
        if operation.id in graph:
            raise ValueError("duplicate compiled node")
        graph.add_node(operation.id, operation=operation)
    if any(a not in graph or b not in graph for a, b in value["edges"]):
        raise ValueError("compiled edge references unknown node")
    graph.add_edges_from(value["edges"])
    return CompiledCircuit(value["num_qubits"], graph, tuple(value["rotations"]))

def save_compilation(path, circuit, processor, schedule, metadata=None):
    report = validate_schedule(circuit, processor, schedule)
    payload = {"schema_version": 1, "processor": processor.to_dict(),
        "circuit": compiled_circuit_to_dict(circuit),
        "schedule": schedule.to_dict(), "validation": report, "metadata": metadata or {}}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_compilation(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data["schema_version"] != 1:
        raise ValueError("unsupported compilation schema")
    config = data["processor"]["config"].copy()
    # Historical artifacts used d sites per side. Preserve their saved geometry;
    # new artifacts serialize the resolved 2*d-1 default explicitly.
    if config.get("site_grid_size") is None:
        config["site_grid_size"] = config["d"]
    config.setdefault("geometry_model", "legacy")
    processor = Processor(ProcessorConfig(**config))
    circuit = compiled_circuit_from_dict(data["circuit"])
    schedule = RoutingSchedule.from_dict(data["schedule"])
    validate_schedule(circuit, processor, schedule)
    return circuit, processor, schedule, data["metadata"]


def save_transversal(path, circuit, processor, program):
    payload = transversal_compilation_to_dict(circuit, processor, program)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def transversal_compilation_to_dict(circuit, processor, program):
    from ftqc_patch_rotation.codes.patch_layout import rotated_patch_layout
    from ftqc_patch_rotation.passes.transversal_validation import validate_transversal
    report = validate_transversal(circuit, processor, program)
    schema = f"ftqc.transversal-compilation.v{program.schema_version}"
    payload = {"schema": schema, "processor": processor.to_dict(),
               "patch_layout": rotated_patch_layout(processor.config.d, processor.site_grid_size).to_dict(),
               "circuit": compiled_circuit_to_dict(circuit), "program": program.to_dict(), "validation": report}
    if program.transport_mode == "bloqade-lanes":
        payload = _renumber_compilation(payload)
        payload["patch_id_numbering"] = "bus-facing-rows"
    return payload


def load_transversal(path):
    return transversal_compilation_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def transversal_compilation_from_dict(payload):
    from ftqc_patch_rotation.codes.patch_layout import rotated_patch_layout
    from ftqc_patch_rotation.ir.transversal import TransversalProgram
    from ftqc_patch_rotation.passes.transversal_validation import validate_transversal
    if payload.get("schema") not in {"ftqc.transversal-compilation.v2", "ftqc.transversal-compilation.v3", "ftqc.transversal-compilation.v4"}:
        raise ValueError("unsupported transversal compilation")
    if payload.get("patch_id_numbering") == "bus-facing-rows":
        payload = _renumber_compilation(payload)
    elif "patch_id_numbering" in payload:
        raise ValueError("unsupported patch ID numbering")
    config = payload["processor"]["config"].copy()
    config.setdefault("geometry_model", "legacy")
    processor = Processor(ProcessorConfig(**config))
    if payload["patch_layout"] != rotated_patch_layout(processor.config.d, processor.site_grid_size).to_dict():
        raise ValueError("transversal patch layout disagrees with code geometry")
    circuit = compiled_circuit_from_dict(payload["circuit"])
    program = TransversalProgram.from_dict(payload["program"])
    expected_schema = f"ftqc.transversal-compilation.v{program.schema_version}"
    if payload["schema"] != expected_schema:
        raise ValueError("transversal compilation and program schemas disagree")
    validate_transversal(circuit, processor, program)
    return circuit, processor, program


def save_timed_transversal(path, circuit, processor, program, timed):
    from ftqc_patch_rotation.passes.timing import validate_transversal_timing
    report = validate_transversal_timing(circuit, processor, program, timed)
    payload = {"schema": "ftqc.timed-transversal-compilation.v1",
               "compilation": transversal_compilation_to_dict(circuit, processor, program),
               "timing": timed.to_dict(), "timing_validation": report}
    if program.transport_mode == "bloqade-lanes":
        payload["timing"] = renumber_bus_output(payload["timing"], processor.config.a1)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_timed_transversal(path):
    from ftqc_patch_rotation.ir.timing import TimedTransversalProgram
    from ftqc_patch_rotation.passes.timing import validate_transversal_timing
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != "ftqc.timed-transversal-compilation.v1":
        raise ValueError("unsupported timed transversal compilation")
    circuit, processor, program = transversal_compilation_from_dict(payload["compilation"])
    timing = payload["timing"]
    if payload["compilation"].get("patch_id_numbering") == "bus-facing-rows":
        timing = renumber_bus_output(timing, processor.config.a1)
    timed = TimedTransversalProgram.from_dict(timing)
    validate_transversal_timing(circuit, processor, program, timed)
    return circuit, processor, program, timed
