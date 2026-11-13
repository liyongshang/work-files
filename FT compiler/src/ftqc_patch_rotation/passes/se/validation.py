"""Replay the SE atom schedule and validate pickup, gate pairs and role changes."""
from dataclasses import replace

from .aod import apply_aod
from .layout import validate_restored
from .planning import plan_layer


def apply_instruction(processor, state, op):
    if op.kind == "aod":
        apply_aod(state, op)
    elif op.kind in ("entangle", "roles"):
        ids = [q for pair in op.pairs for q in pair]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("entangling pairs must be nonempty and disjoint")
        offset = tuple(a-d for a, d in zip(processor.patch_anchor(state.ancilla_patch),
                                          processor.patch_anchor(state.data_patch)))
        for dq, aq in op.pairs:
            d, a = state.atoms[dq], state.atoms[aq]
            if (d.role, a.role) != ("D", "A") or (a.x-d.x, a.y-d.y) != offset:
                raise ValueError("gate pair has incorrect roles or site-pair separation")
        if op.kind == "roles":
            for dq, aq in op.pairs:
                state.atoms[dq] = replace(state.atoms[dq], role="A")
                state.atoms[aq] = replace(state.atoms[aq], role="D")
            state.data_patch, state.ancilla_patch = state.ancilla_patch, state.data_patch
    else:
        raise ValueError(f"unknown SE instruction {op.kind}")


def validate_se_program(processor, program):
    if program.distance != processor.config.d:
        raise ValueError("SE distance disagrees with processor")
    if len(set(program.swap_directions)) != len(program.swap_directions) or not set(program.swap_directions) <= set("LRUD"):
        raise ValueError("invalid swap directions")
    state = program.initial.copy()
    validate_restored(processor, state)
    frames = [state.copy()]
    offset = 0
    for direction in "LRUD":
        layer = plan_layer(processor, state, direction, direction in program.swap_directions)
        actual = program.instructions[offset:offset+len(layer.instructions)]
        if tuple(actual) != layer.instructions:
            raise ValueError(f"{direction}: instructions disagree with the SE motion contract")
        for op in actual:
            apply_instruction(processor, state, op)
            frames.append(state.copy())
        validate_restored(processor, state)
        offset += len(actual)
    if offset != len(program.instructions):
        raise ValueError("unexpected trailing SE instructions")
    return frames
