"""Replay the emitted hardware schedule independently of planner state."""
import networkx as nx
from ftqc_patch_rotation.errors import RoutingError
from .aod import apply_stage
from .blocks import build_cz_blocks
from .semantics import CZ, DEFORMATION, _check_input, _check_mapping, _check_gate_group, _update_state

def validate_schedule(circuit, processor, schedule):
    """Independent replay of emitted instructions, not the planner's internal state."""
    _check_input(circuit)
    _check_mapping(schedule.mapping, circuit, processor)
    expected_blocks = build_cz_blocks(circuit)
    if schedule.cz_blocks != expected_blocks:
        raise RoutingError("serialized CZ blocks disagree with input")
    block_of = {n: index for index, b in enumerate(expected_blocks) for n in b}
    ancestors = {n: nx.ancestors(circuit.dag, n) for n in circuit.dag}
    remaining, done = set(circuit.dag), set()
    pos = schedule.mapping.initial_data_patch.copy()
    storage_owners = ({p: q for q, p in schedule.mapping.initial_data_patch.items()}
                      if processor.config.code_kind == "rotated_surface" else None)
    orientation, epochs = [False]*circuit.num_qubits, [0]*circuit.num_qubits
    for block in schedule.blocks:
        ordinary_ready = {n for n in remaining if circuit.operation(n).kind not in CZ | DEFORMATION
                          and not ancestors[n].intersection(remaining)}
        deformation_ready = {n for n in remaining if circuit.operation(n).kind in DEFORMATION
                             and not ancestors[n].intersection(remaining)}
        if block.kind != "ordinary" and ordinary_ready:
            raise RoutingError("ordinary instruction priority violated")
        if block.kind in {"aod", "cz"} and deformation_ready:
            raise RoutingError("deformation instruction priority violated")
        if block.kind == "aod":
            if block.nodes:
                raise RoutingError("AOD block includes logical operations")
            apply_stage(pos, block.moves, processor, storage_owners=storage_owners)
            continue
        if block.kind not in {"ordinary", "deformation", "cz"} or not block.nodes or block.moves:
            raise RoutingError("invalid instruction block")
        if block.kind == "cz":
            _check_gate_group(block.nodes, circuit, pos, processor, orientation)
        for n in block.nodes:
            if n not in remaining:
                raise RoutingError(f"duplicate/unknown instruction {n}")
            op = circuit.operation(n)
            expected_kind = "cz" if op.kind in CZ else "deformation" if op.kind in DEFORMATION else "ordinary"
            if block.kind != expected_kind:
                raise RoutingError("incorrect operation category")
            predecessors = ancestors[n] & remaining
            if block.kind == "cz":
                predecessors = {p for p in predecessors if block_of.get(p) != block_of[n]}
                if any(block_of.get(p, block_of[n]) < block_of[n] for p in remaining):
                    raise RoutingError("CZ blocks scheduled out of order")
            if predecessors:
                raise RoutingError(f"unfinished predecessors at {n}: {predecessors}")
            _update_state(op, orientation, epochs)
            remaining.remove(n)
            done.add(n)
    if remaining or pos != schedule.final_positions:
        raise RoutingError("incomplete schedule or incorrect final positions")
    return {"valid": True, "operations": len(done), "aod_stages": schedule.stage_count,
            "final_orientation": orientation, "reset_epochs": epochs}
