"""Orchestrate patch routing and hardware instruction emission."""
import random
import networkx as nx
from ftqc_patch_rotation.errors import RoutingError
from ftqc_patch_rotation.ir.routing import InstructionBlock, RoutingSchedule
from .blocks import build_cz_blocks
from .mapping import initial_mapping
from .placement import partition_block, assign_positions
from .aod import plan_aod_stages, apply_stage
from .semantics import CZ, DEFORMATION, _check_mapping, _check_gate_group, _update_state
from .validation import validate_schedule

def route_and_schedule(circuit, processor, mapping=None, cost_fn=len, seed=0):
    blocks = build_cz_blocks(circuit)
    mapping = mapping or initial_mapping(range(circuit.num_qubits), blocks, circuit, processor)
    _check_mapping(mapping, circuit, processor)
    pos = mapping.initial_data_patch.copy()
    storage_homes = mapping.initial_data_patch if processor.config.code_kind == "rotated_surface" else None
    storage_owners = {p: q for q, p in storage_homes.items()} if storage_homes is not None else None
    remaining = set(circuit.dag)
    ancestors = {n: nx.ancestors(circuit.dag, n) for n in remaining}
    bs = [list(b) for b in blocks]
    groups, output = [], []
    orientations, epochs = [False]*circuit.num_qubits, [0]*circuit.num_qubits
    rng = random.Random(seed)
    def ready(kinds, exclude=False):
        return sorted(n for n in remaining if (circuit.operation(n).kind in kinds) != exclude
                      and not ancestors[n].intersection(remaining))
    def record(nodes, kind):
        output.append(InstructionBlock(kind, tuple(nodes)))
        for n in nodes:
            _update_state(circuit.operation(n), orientations, epochs)
            remaining.remove(n)
    while remaining:
        ordinary = []
        while True:
            front = ready(CZ | DEFORMATION, exclude=True)
            if not front:
                break
            for n in front:
                _update_state(circuit.operation(n), orientations, epochs)
                remaining.remove(n)
                ordinary.append(n)
        if ordinary:
            output.append(InstructionBlock("ordinary", tuple(ordinary)))
        front = ready(DEFORMATION)
        if front:
            record(front, "deformation")
            continue
        if not remaining:
            break
        while bs and not bs[0]:
            bs.pop(0)
        if not bs:
            raise RoutingError("remaining operations but no CZ block")
        if not groups:
            groups = partition_block(bs[0], circuit, processor.pair_count)
        group = groups.pop(0)
        for n in group:
            if (ancestors[n] & remaining) - set(bs[0]):
                raise RoutingError(f"unfinished external predecessor for CZ block node {n}")
        target = assign_positions(group, circuit, pos, processor, rng, storage_homes=storage_homes)
        _check_gate_group(group, circuit, target, processor, orientations)
        stages = plan_aod_stages(pos, target, processor, storage_owners=storage_owners)
        for stage in stages:
            output.append(InstructionBlock("aod", moves=stage))
            apply_stage(pos, stage, processor, storage_owners=storage_owners)
        record(group, "cz")
        bs[0] = [n for n in bs[0] if n not in group]
    result = RoutingSchedule(mapping, output, blocks, pos, seed,
                            cost_fn([b.moves for b in output if b.kind == "aod"]))
    validate_schedule(circuit, processor, result)
    return result
