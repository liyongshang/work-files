"""Dependency/resource constrained list scheduling of transversal instructions.

No change to the validated routing plan or gate recipes. Operation classes are
globally exclusive. Deformations exclusively reserve the mobility class.
"""
import math
from fractions import Fraction
from dataclasses import replace

import networkx as nx

from ftqc_patch_rotation.codes import rotated_patch_layout
from ftqc_patch_rotation.ir.timing import (
    TimingConfig, TimedInstruction, TimedStep, TimedTransversalProgram,
    PARALLEL_SCHEDULE, finite_nonnegative)
from ftqc_patch_rotation.passes.routing.aod import compatible_segments
from ftqc_patch_rotation.passes.timing import (_offset_targets, _specs, requires_aod,
    aod_conflict, validate_aod_allocation)
from ftqc_patch_rotation.passes.transversal_validation import validate_transversal


def operation_class(instruction):
    if instruction.kind in {"block_move", "block_offset", "deformation"}:
        return "mobility"
    if instruction.kind in {"resource_prepare", "logical_measurement"} or instruction.name in {"reset", "measure"}:
        return "measurement/preparation"
    if instruction.kind == "transversal_gate":
        return "gate"
    return "barrier"


def execution_dependencies(circuit, processor, program, specs):
    """Preserve logical/macro order, blocks, and actual patch-occupancy history."""
    checks = {site: (x, y) for site, x, y in rotated_patch_layout(
        processor.config.d, processor.site_grid_size).checks}
    graph = nx.DiGraph()
    graph.add_nodes_from(range(len(specs)))
    by_step = [[] for _ in program.steps]
    for index, spec in enumerate(specs):
        by_step[spec[1]].append(index)
    positions = {**{2*q: p for q, p in program.mapping.initial_data_patch.items()},
                 **{2*q+1: p for q, p in program.mapping.ancilla_patch.items()}}
    last_block, patch_history, node_spans, motions = {}, {}, {}, {}
    for step_index, step in enumerate(program.steps):
        indices = by_step[step_index]
        graph.add_edges_from(zip(indices, indices[1:]))
        blocks = {b for i in indices for b in specs[i][6]}
        # An SE is atomic with respect to subsequent use of both code blocks,
        # including its final ancilla readout after the last data interaction.
        if step.kind in {"se", "se_interaction", "se_readout"}:
            blocks.update((2*step.logical_qubit, 2*step.logical_qubit+1))
        for block in blocks:
            if block in last_block:
                graph.add_edge(last_block[block], indices[0])
            last_block[block] = indices[-1]
        if step.node_id is not None:
            first = node_spans.get(step.node_id, (indices[0], indices[-1]))[0]
            node_spans[step.node_id] = (first, indices[-1])
        offsets = {}
        for index in indices:
            accesses, segments = {}, []
            if step.kind == "block_move":
                for move in step.moves:
                    for patch in (move.start, move.target):
                        accesses.setdefault(patch, set()).add(move.qubit)
                    segments.append((processor.patch_anchor(move.start), processor.patch_anchor(move.target)))
                if step.transport.get("path_model") == "site-roads-v1":
                    segments = [tuple(tuple(Fraction(v) for v in point) for point in record["waypoints"])
                                for record in step.transport["atom_paths"]]
                positions.update({m.qubit: m.target for m in step.moves})
            else:
                action = step.actions[specs[index][2]]
                for block in action.blocks:
                    accesses.setdefault(positions[block], set()).add(block)
                if action.kind == "block_offset":
                    block = action.blocks[0]
                    patch = positions[block]
                    origin = processor.patch_anchor(patch)
                    pitch = ((processor.px, processor.py) if processor.zone_of(patch) == "entanglement"
                             else (processor.s, processor.s))
                    targets = _offset_targets(action, checks)
                    if action.targets:
                        for target in targets:
                            before = offsets.get(target, (0, 0))
                            local = checks[target[1]]
                            segments.append((tuple(origin[a]+(local[a]+before[a])*pitch[a] for a in (0, 1)),
                                             tuple(origin[a]+(local[a]+action.offset[a])*pitch[a] for a in (0, 1))))
                    else:
                        # Preserve the patch-anchor abstraction of historical
                        # whole-block programs and their saved overlap checks.
                        before = offsets.get(targets[0], (0, 0))
                        segments.append((tuple(origin[a]+before[a]*pitch[a] for a in (0, 1)),
                                         tuple(origin[a]+action.offset[a]*pitch[a] for a in (0, 1))))
                    offsets.update((target, action.offset) for target in targets)
            motions[index] = segments
            for patch, users in accesses.items():
                frontier = patch_history.setdefault(patch, {})
                previous_entries = {previous: previous_users for previous, previous_users in frontier.values()}
                consumed = set()
                for previous, previous_users in previous_entries.items():
                    # Different subblocks of one code can share storage sites;
                    # entanglement members are exclusive even within one code.
                    shareable = (processor.zone_of(patch) == "storage"
                                 and len({b//2 for b in users | previous_users}) == 1)
                    if not shareable and previous != index:
                        graph.add_edge(previous, index)
                        consumed.add(previous)
                # Keep only the occupancy frontier, rather than adding an
                # edge to every historical use of a frequently reused pair.
                for block in list(frontier):
                    if frontier[block][0] in consumed:
                        del frontier[block]
                for block in users:
                    frontier[block] = (index, users)
    for before, after in circuit.dag.edges:
        graph.add_edge(node_spans[before][1], node_spans[after][0])
    if not nx.is_directed_acyclic_graph(graph):
        raise ValueError("transversal execution dependency cycle")
    return graph, motions, by_step


def _overlap(a, b):
    # Empty intervals do not occupy resources. Boundaries may touch.
    return a.duration > 0 and b.duration > 0 and max(a.start_time, b.start_time) < min(a.end_time, b.end_time)


def _point(segment, instruction, time):
    fraction = (time-instruction.start_time)/instruction.duration
    lengths = [math.hypot(float(b[0]-a[0]), float(b[1]-a[1])) for a, b in zip(segment, segment[1:])]
    remaining = fraction*sum(lengths)
    for (start, end), length in zip(zip(segment, segment[1:]), lengths):
        if remaining <= length and length:
            return tuple(float(start[a])+remaining/length*float(end[a]-start[a]) for a in (0, 1))
        remaining -= length
    return tuple(map(float, segment[-1]))


def _turn_times(segment, instruction):
    lengths = [math.hypot(float(b[0]-a[0]), float(b[1]-a[1])) for a, b in zip(segment, segment[1:])]
    total, elapsed = sum(lengths), 0.0
    if total:
        for length in lengths[:-1]:
            elapsed += length
            yield instruction.start_time+instruction.duration*elapsed/total


def can_overlap(a, b, segments_a, segments_b):
    if not _overlap(a, b):
        return True
    if set(a.blocks) & set(b.blocks):
        return False
    ca, cb = operation_class(a), operation_class(b)
    if ca != cb:
        return False
    if ca == cb == "gate":
        return a.name == b.name
    if ca == cb == "mobility":
        if a.kind == "deformation" or b.kind == "deformation":
            return False  # no internal motion model to establish compatibility
        ta, tb = a.instruction.get("transport"), b.instruction.get("transport")
        if ta and tb and ta["bus_id"] == tb["bus_id"]:
            # Each emitted group is one uniform-direction BUS execution.
            # Separate executions on the same bus remain ordered.
            return False
        start, end = max(a.start_time, b.start_time), min(a.end_time, b.end_time)
        for sa in segments_a:
            for sb in segments_b:
                turns = sorted({start, end, *(t for t in _turn_times(sa, a) if start < t < end),
                                *(t for t in _turn_times(sb, b) if start < t < end)})
                if any(not compatible_segments(_point(sa, a, left), _point(sa, a, right),
                                               _point(sb, b, left), _point(sb, b, right))
                       for left, right in zip(turns, turns[1:])):
                    return False
        return True
    return True


def time_parallel_transversal(circuit, processor, program, config=None):
    validate_transversal(circuit, processor, program)
    config = TimingConfig() if config is None else config
    config.validate()
    specs = list(_specs(program, processor, config))
    if set(config.duration_overrides_ns)-{s[0] for s in specs}:
        raise ValueError("duration override references unknown instruction ID")
    graph, motions, by_step = execution_dependencies(circuit, processor, program, specs)
    remaining, scheduled = set(graph), {}

    def earliest(index):
        key, si, ai, node, kind, name, blocks, distance, payload, base = specs[index]
        duration = config.duration_overrides_ns.get(key, base)
        finite_nonnegative(duration, f"duration {key}")
        start = max((scheduled[p].end_time for p in graph.predecessors(index)), default=float(config.start_time_ns))
        while True:
            candidate = TimedInstruction(key, si, ai, node, kind, name, blocks, start, duration,
                start+duration, distance, payload, tuple(specs[p][0] for p in sorted(graph.predecessors(index))))
            if requires_aod(candidate):
                for aod_id in range(config.aod_count):
                    assigned = replace(candidate, aod_id=aod_id)
                    if not any(aod_conflict(assigned, old) for old in scheduled.values()):
                        candidate = assigned
                        break
            conflicts = [old.end_time for j, old in scheduled.items()
                         if not can_overlap(candidate, old, motions[index], motions[j])
                         or aod_conflict(candidate, old)
                         or (requires_aod(candidate) and candidate.aod_id is None
                             and requires_aod(old) and _overlap(candidate, old))]
            if not conflicts:
                finite_nonnegative(candidate.end_time, key)
                return candidate
            start = max(conflicts)

    while remaining:
        ready = [i for i in sorted(remaining) if all(p in scheduled for p in graph.predecessors(i))]
        choices = [(earliest(i), i) for i in ready]
        chosen, index = min(choices, key=lambda entry: (entry[0].start_time, entry[1]))
        scheduled[index] = chosen
        remaining.remove(index)
    instructions = tuple(scheduled[i] for i in range(len(specs)))
    steps = []
    for index, indices in enumerate(by_step):
        leaves = [scheduled[i] for i in indices]
        start, end = min(i.start_time for i in leaves), max(i.end_time for i in leaves)
        step = program.steps[index]
        steps.append(TimedStep(index, step.kind, step.node_id, step.logical_gate,
            start, end-start, end, tuple(i.id for i in leaves)))
    end = max((i.end_time for i in instructions), default=float(config.start_time_ns))
    return TimedTransversalProgram(config, tuple(steps), instructions, float(config.start_time_ns),
                                   end-config.start_time_ns, end, PARALLEL_SCHEDULE)


def validate_parallel_timing(circuit, processor, program, timed):
    """Validate dependencies, exact costs, all overlapping resources and totals."""
    validate_transversal(circuit, processor, program)
    timed.config.validate()
    validate_aod_allocation(timed)
    specs = list(_specs(program, processor, timed.config))
    graph, motions, by_step = execution_dependencies(circuit, processor, program, specs)
    if len(specs) != len(timed.instructions) or len(timed.steps) != len(program.steps):
        raise ValueError("incomplete parallel timing")
    if set(timed.config.duration_overrides_ns)-{s[0] for s in specs}:
        raise ValueError("unknown duration override")
    def same(actual, expected):
        finite_nonnegative(actual, "parallel timing value")
        if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-8):
            raise ValueError("parallel timing cost or summary mismatch")
    for index, (instruction, spec) in enumerate(zip(timed.instructions, specs)):
        key, si, ai, node, kind, name, blocks, distance, payload, base = spec
        if ((instruction.id, instruction.step_index, instruction.action_index, instruction.node_id,
             instruction.kind, instruction.name, instruction.blocks, instruction.instruction,
             instruction.predecessors) != (key, si, ai, node, kind, name, blocks, payload,
                tuple(specs[p][0] for p in sorted(graph.predecessors(index))))):
            raise ValueError("parallel instruction or dependencies disagree with IR")
        if distance is None:
            if instruction.distance_um is not None:
                raise ValueError("unexpected distance")
        else:
            same(instruction.distance_um, distance)
        same(instruction.duration, timed.config.duration_overrides_ns.get(key, base))
        same(instruction.end_time, instruction.start_time+instruction.duration)
        if instruction.start_time < timed.config.start_time_ns:
            raise ValueError("instruction starts before schedule origin")
        if any(timed.instructions[p].end_time > instruction.start_time+1e-8 for p in graph.predecessors(index)):
            raise ValueError("parallel dependency violation")
        for j in range(index):
            if not can_overlap(instruction, timed.instructions[j], motions[index], motions[j]):
                raise ValueError("parallel gate/AOD/block resource conflict")
    for index, indices in enumerate(by_step):
        step, summary = program.steps[index], timed.steps[index]
        leaves = [timed.instructions[i] for i in indices]
        if ((summary.step_index, summary.kind, summary.node_id, summary.logical_gate, summary.instruction_ids)
                != (index, step.kind, step.node_id, step.logical_gate, tuple(i.id for i in leaves))):
            raise ValueError("incorrect parallel step summary")
        start, end = min(i.start_time for i in leaves), max(i.end_time for i in leaves)
        same(summary.start_time, start)
        same(summary.end_time, end)
        same(summary.duration, end-start)
    end = max((i.end_time for i in timed.instructions), default=float(timed.config.start_time_ns))
    same(timed.start_time, timed.config.start_time_ns)
    same(timed.end_time, end)
    same(timed.duration, end-timed.start_time)
    return {"valid": True, "instructions": len(specs), "duration": timed.duration,
            "start_time": timed.start_time, "end_time": timed.end_time, "time_unit": "ns",
            "schedule_kind": "parallel"}
