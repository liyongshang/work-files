"""Assign serial start/duration/end times to validated transversal instructions."""
from dataclasses import asdict
import json
import math

from ftqc_patch_rotation.codes import rotated_surface_layout
from ftqc_patch_rotation.ir.timing import (
    TimingConfig, TimedInstruction, TimedStep, TimedTransversalProgram, finite_nonnegative)
from ftqc_patch_rotation.passes.transversal_validation import validate_transversal


def _offset_targets(action, check_ids):
    """Explicit check selectors, or the whole check block in legacy programs."""
    return action.targets or tuple((action.blocks[0], site) for site in check_ids)


def requires_aod(instruction):
    return instruction.kind in {"block_move", "block_offset"}


def aod_conflict(a, b):
    return (a.aod_id is not None and a.aod_id == b.aod_id
            and a.duration > 0 and b.duration > 0
            and max(a.start_time, b.start_time) < min(a.end_time, b.end_time))


def validate_aod_allocation(timed):
    for index, instruction in enumerate(timed.instructions):
        if requires_aod(instruction):
            if type(instruction.aod_id) is not int or not 0 <= instruction.aod_id < timed.config.aod_count:
                raise ValueError("missing or invalid AOD allocation")
        elif instruction.aod_id is not None:
            raise ValueError("non-AOD instruction has an AOD allocation")
        if any(aod_conflict(instruction, other) for other in timed.instructions[:index]):
            raise ValueError("AOD is occupied by overlapping operations")


def _specs(program, processor, config):
    check_ids = tuple(check.id for check in rotated_surface_layout(processor.config.d).checks)
    positions = {**{2*q: p for q, p in program.mapping.initial_data_patch.items()},
                 **{2*q+1: p for q, p in program.mapping.ancilla_patch.items()}}
    for index, step in enumerate(program.steps):
        if step.kind == "block_move":
            if step.transport.get("path_model") == "site-roads-v1":
                from ftqc_patch_rotation.roads import path_length
                distance = max(path_length(path["waypoints"]) for path in step.transport["atom_paths"])
            else:
                distance = max(math.sqrt(float(processor.distance2(m.start, m.target))) for m in step.moves)
            positions.update({m.qubit: m.target for m in step.moves})
            payload = {"moves": [asdict(m) for m in step.moves]}
            if step.transport:
                payload["transport"] = step.transport
            yield (f"s{index}", index, None, step.node_id, "block_move", "move",
                   tuple(m.qubit for m in step.moves), distance,
                   payload, distance*config.move_ns_per_um)
            continue
        offsets = {}
        for action_index, action in enumerate(step.actions):
            distance = None
            if action.kind == "block_offset":
                block = action.blocks[0]
                pitch = (processor.px, processor.py) if processor.zone_of(positions[block]) == "entanglement" else (processor.s, processor.s)
                targets = _offset_targets(action, check_ids)
                distance = max(math.hypot(*(float((action.offset[i]-offsets.get(target, (0, 0))[i])*pitch[i])
                                           for i in (0, 1))) for target in targets)
                offsets.update((target, action.offset) for target in targets)
                name, duration = "offset", distance*config.move_ns_per_um
            elif action.kind in {"transversal_gate", "resource_prepare", "logical_measurement"}:
                name = action.gate
                if name not in config.gate_durations_ns:
                    raise ValueError(f"no duration configured for gate {name}")
                duration = config.gate_durations_ns[name]
            elif action.kind == "deformation":
                name = action.deformation
                if name not in config.deformation_durations_ns:
                    raise ValueError(f"no duration configured for deformation {name}")
                duration = config.deformation_durations_ns[name]
            elif action.kind == "barrier":
                name, duration = "barrier", 0.0
            else:
                raise ValueError(f"no timing model for action {action.kind}")
            payload = json.loads(json.dumps(asdict(action)))
            yield (f"s{index}.a{action_index}", index, action_index, step.node_id,
                   action.kind, name, action.blocks, distance, payload, duration)


def time_transversal(circuit, processor, program, config=None, *, scheduling="serial"):
    if scheduling == "parallel":
        from ftqc_patch_rotation.passes.parallel_timing import time_parallel_transversal
        return time_parallel_transversal(circuit, processor, program, config)
    if scheduling != "serial":
        raise ValueError("unknown transversal scheduling policy")
    validate_transversal(circuit, processor, program)
    config = TimingConfig() if config is None else config
    config.validate()
    clock, instructions = float(config.start_time_ns), []
    for key, si, ai, node, kind, name, blocks, distance, payload, base_duration in _specs(program, processor, config):
        duration = config.duration_overrides_ns.get(key, base_duration)
        finite_nonnegative(duration, f"duration {key}")
        end = clock+duration
        finite_nonnegative(end, f"end_time {key}")
        instructions.append(TimedInstruction(key, si, ai, node, kind, name, blocks,
                                             clock, duration, end, distance, payload,
                                             aod_id=0 if kind in {"block_move", "block_offset"} else None))
        clock = end
    if set(config.duration_overrides_ns)-{i.id for i in instructions}:
        raise ValueError("duration override references unknown instruction ID")
    by_step = [[] for _ in program.steps]
    for instruction in instructions:
        by_step[instruction.step_index].append(instruction)
    steps = []
    for index, (step, leaves) in enumerate(zip(program.steps, by_step)):
        start, end = leaves[0].start_time, leaves[-1].end_time
        steps.append(TimedStep(index, step.kind, step.node_id, step.logical_gate,
            start, end-start, end, tuple(i.id for i in leaves)))
    return TimedTransversalProgram(config, tuple(steps), tuple(instructions),
                                   float(config.start_time_ns), clock-config.start_time_ns, clock)


def validate_transversal_timing(circuit, processor, program, timed):
    """Recompute costs and replay clock continuity; do not trust stored totals."""
    from ftqc_patch_rotation.ir.timing import SERIAL_SCHEDULE, PARALLEL_SCHEDULE
    if timed.schedule_kind == PARALLEL_SCHEDULE:
        from ftqc_patch_rotation.passes.parallel_timing import validate_parallel_timing
        return validate_parallel_timing(circuit, processor, program, timed)
    if timed.schedule_kind != SERIAL_SCHEDULE:
        raise ValueError("unknown transversal schedule kind")
    validate_transversal(circuit, processor, program)
    timed.config.validate()
    validate_aod_allocation(timed)
    specs = list(_specs(program, processor, timed.config))
    if len(timed.instructions) != len(specs) or len(timed.steps) != len(program.steps):
        raise ValueError("timing does not cover every transversal instruction")
    def same(actual, expected):
        finite_nonnegative(actual, "stored timing value")
        if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-8):
            raise ValueError("timing cost or clock continuity mismatch")
    clock = float(timed.config.start_time_ns)
    groups = [[] for _ in program.steps]
    for instruction, spec in zip(timed.instructions, specs):
        key, si, ai, node, kind, name, blocks, distance, payload, base_duration = spec
        if ((instruction.id, instruction.step_index, instruction.action_index, instruction.node_id,
             instruction.kind, instruction.name, instruction.blocks, instruction.instruction)
                != (key, si, ai, node, kind, name, blocks, payload)):
            raise ValueError("timed instruction disagrees with transversal IR")
        if distance is None:
            if instruction.distance_um is not None:
                raise ValueError("unexpected movement distance")
        else:
            same(instruction.distance_um, distance)
        duration = timed.config.duration_overrides_ns.get(key, base_duration)
        same(instruction.start_time, clock)
        same(instruction.duration, duration)
        clock += duration
        same(instruction.end_time, clock)
        groups[si].append(instruction)
    if set(timed.config.duration_overrides_ns)-{i.id for i in timed.instructions}:
        raise ValueError("unknown duration override")
    for index, (stored, step, leaves) in enumerate(zip(timed.steps, program.steps, groups)):
        if ((stored.step_index, stored.kind, stored.node_id, stored.logical_gate, stored.instruction_ids)
                != (index, step.kind, step.node_id, step.logical_gate, tuple(i.id for i in leaves))):
            raise ValueError("incorrect timed step summary")
        same(stored.start_time, leaves[0].start_time)
        same(stored.end_time, leaves[-1].end_time)
        same(stored.duration, leaves[-1].end_time-leaves[0].start_time)
    same(timed.start_time, timed.config.start_time_ns)
    same(timed.end_time, clock)
    same(timed.duration, clock-timed.start_time)
    return {"valid": True, "instructions": len(specs), "start_time": timed.start_time,
            "duration": timed.duration, "end_time": timed.end_time, "time_unit": "ns"}
