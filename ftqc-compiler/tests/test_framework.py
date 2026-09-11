import json
import random
from dataclasses import replace

import networkx as nx
import pytest
from qiskit import QuantumCircuit

from ftqc_patch_rotation.compiler import CompiledCircuit, CompiledNode, compile_circuit
from ftqc_patch_rotation.hardware import Processor, ProcessorConfig
from ftqc_patch_rotation.pipeline import compile_processor, load_compilation, save_compilation
from ftqc_patch_rotation.routing import (
    Move, RoutingError, apply_stage, build_cz_blocks, initial_mapping,
    partition_block, plan_aod_stages, route_and_schedule, validate_schedule,
)


def processor():
    return Processor(ProcessorConfig(d=3, a1=4, b1=5, a2=3, b2=2))


def dag(operations, edges, qubits=4):
    graph = nx.DiGraph()
    for i, (kind, qs) in enumerate(operations):
        graph.add_node(i, operation=CompiledNode(i, kind, qs))
    graph.add_edges_from(edges)
    return CompiledCircuit(qubits, graph, ())


def test_geometry_exact_pitch_and_site_extents():
    p = processor()
    assert p.patch_anchor("storage:0:0") == (0, 0)
    assert p.patch_anchor("entanglement:0:0:1")[0] == p.s/5
    assert p.site_position(("entanglement:0:0:0", 0, 1))[0] == 2*p.s
    assert p.site_position(("measurement:3:4", 2, 2))[1] == p.H
    assert p.patch_anchor("entanglement:0:0:0")[1] - p.site_position(("storage:3:0", 2, 0))[1] == 2*p.s
    assert len(p.data_patches) == len(p.ancilla_patches) == 10
    with pytest.raises(ValueError):
        Processor(replace(p.config, H=1))
    with pytest.raises(ValueError):
        Processor(replace(p.config, L=1))
    odd = Processor(ProcessorConfig(3, 3, 2, 1, 1))
    assert len(odd.data_patches) == 2 and len(odd.ancilla_patches) == 4


def test_priority_block_examples():
    c = dag([("cz", (0,1)), ("h", (0,)), ("cz", (0,1)), ("cz", (2,3))], [(0,1),(1,2)])
    assert build_cz_blocks(c) == ((0,3),(2,))
    c = dag([("h", (0,)), ("cz", (0,1)), ("cz", (2,3))], [(0,1)])
    assert build_cz_blocks(c) == ((1,2),)


def test_coloring_duplicates_icz_and_pair_limit():
    c = dag([("cz", (0,1)), ("icz", (0,)), ("cz", (0,1)), ("icz", (2,))], [])
    groups = partition_block((0,1,2,3), c, 2)
    assert sorted(n for g in groups for n in g) == [0,1,2,3]
    for g in groups:
        operands = [q for n in g for q in c.operation(n).qubits]
        assert len(operands) == len(set(operands)) and len(g) <= 2


def test_mapping_capacity_and_initial_only():
    p = processor()
    c = dag([("icz", (3,)), ("cz", (0,1))], [(0,1)])
    m = initial_mapping(range(4), ((0,), (1,)), c, p)
    assert list(m.initial_data_patch) == [3,0,1,2]
    with pytest.raises(RoutingError, match="capacity"):
        initial_mapping(range(11), (), c, p)


def test_dependency_can_share_stage():
    p = processor()
    a,b,c = p.data_patches[:3]
    pos = {0:a, 1:b}
    stages = plan_aod_stages(pos, {0:b, 1:c}, p)
    assert len(stages) == 1
    assert [m.qubit for m in stages[0]] == [1,0]
    apply_stage(pos, stages[0], p)
    assert pos == {0:b, 1:c}


def test_dependency_waits_when_non_crossing_prevents_same_stage():
    p = processor()
    a,b = p.data_patches[:2]
    c = p.data_patches[5]
    stages = plan_aod_stages({0:a, 1:b}, {0:b, 1:c}, p)
    assert len(stages) == 2
    assert stages[0][0].qubit == 1
    assert stages[1][0].qubit == 0


def test_priority_does_not_reverse_dependency():
    p = processor()
    a = p.data_patches[0]
    b,c = p.pair_members("pair:0:0")
    # Returning q0 must wait for q1 to leave its destination, despite n_in priority.
    stages = plan_aod_stages({0:b,1:a}, {0:a,1:c}, p)
    index = {m.qubit:i for i,s in enumerate(stages) for m in s}
    assert index[1] <= index[0]


def test_cycle_uses_nearest_unused_empty_buffer():
    p = processor()
    a,b = p.data_patches[:2]
    pos, target = {0:a,1:b}, {0:b,1:a}
    stages = plan_aod_stages(pos, target, p)
    free = set(p.data_patches) | {m for pair in p.pairs.values() for m in pair}
    free -= {a,b}
    distance = min(p.distance2(pos[q], patch) for q in pos for patch in free)
    first = stages[0][0]
    assert p.distance2(first.start,first.target) == distance
    assert first.target not in {a,b}
    replay = pos.copy()
    for stage in stages:
        apply_stage(replay, stage, p)
    assert replay == target
    assert pos == {0:a,1:b}


def test_no_empty_buffer_and_invalid_target():
    p = Processor(ProcessorConfig(1,2,1,1,1))
    slots = p.data_patches + p.pair_members("pair:0:0")
    pos = dict(enumerate(slots))
    target = {0:slots[1], 1:slots[0], 2:slots[2]}
    with pytest.raises(RoutingError, match="buffer"):
        plan_aod_stages(pos, target, p)
    a,b = slots[:2]
    with pytest.raises(RoutingError):
        plan_aod_stages({0:a,1:b}, {0:b,1:b}, p)


def test_disjoint_cycles_reserve_different_buffers():
    p = processor()
    a,b,c,d = p.data_patches[:4]
    pos, target = {0:a,1:b,2:c,3:d}, {0:b,1:a,2:d,3:c}
    stages = plan_aod_stages(pos,target,p)
    assert stages[0][0].target != stages[1][0].target
    replay = pos.copy()
    for stage in stages:
        apply_stage(replay,stage,p)
    assert replay == target


def test_crossing_rejected():
    p = processor()
    a,b,c = p.data_patches[:3]
    with pytest.raises(RoutingError, match="non-crossing"):
        apply_stage({0:a,1:c}, (Move(0,a,c), Move(1,c,b)), p)


def test_pipeline_resets_s_and_json_roundtrip(tmp_path):
    c = QuantumCircuit(3)
    c.cz(0,1)
    c.reset(0)
    c.cz(0,2)
    c.s(1)
    compiled, result, meta = compile_processor(c, processor())
    assert sum(op.kind == "rot" for op in compiled.operations()) == 2
    report = validate_schedule(compiled, processor(), result)
    assert report["reset_epochs"] == [1,0,0]
    path = save_compilation(tmp_path/"output.json", compiled, processor(), result, meta)
    _, _, loaded, _ = load_compilation(path)
    assert loaded.to_dict() == result.to_dict()
    result.blocks[-1].nodes = result.blocks[0].nodes
    with pytest.raises(RoutingError):
        validate_schedule(compiled, processor(), result)


def test_static_magic_frontend():
    c = QuantumCircuit(3)
    c.t(0)
    c.ccz(0,1,2)
    compiled, result, meta = compile_processor(c, processor(), seed=7)
    assert compiled.num_qubits == 7
    assert meta["magic_state_conversion"]["t"] == 1
    assert meta["magic_state_conversion"]["ccx"] == 1
    assert validate_schedule(compiled, processor(), result)["valid"]


def test_clifford_random_end_to_end():
    from ftqc_patch_rotation.generator import random_layered_clifford_circuit
    c = random_layered_clifford_circuit(10,10,20260908)
    compiled, a, _ = compile_processor(c, processor(), seed=0)
    b = route_and_schedule(compiled, processor(), seed=0, cost_fn=lambda stages: 2*len(stages))
    assert a.blocks == b.blocks
    assert b.cost == 2*a.stage_count
    assert validate_schedule(compiled, processor(), a)["valid"]


def test_reported_swap_cycle_example_now_completes():
    from ftqc_patch_rotation.generator import random_layered_clifford_circuit
    c = random_layered_clifford_circuit(10,10,20260908)
    compiled, result, _ = compile_processor(c, processor(), seed=20260908)
    assert validate_schedule(compiled, processor(), result)["valid"]
    assert result.stage_count > 0


def test_validator_rejects_delayed_independent_ordinary_gate():
    c = QuantumCircuit(3)
    c.h(2)
    c.cz(0,1)
    compiled, result, _ = compile_processor(c, processor())
    ordinary = result.blocks.pop(0)
    assert ordinary.kind == "ordinary"
    result.blocks.append(ordinary)
    with pytest.raises(RoutingError, match="priority"):
        validate_schedule(compiled, processor(), result)
