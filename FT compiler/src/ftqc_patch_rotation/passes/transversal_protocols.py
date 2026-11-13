"""Adapt verified code circuits into block selectors and SE block offsets."""
from dataclasses import replace

from ftqc_patch_rotation.codes import CodeRepresentation, transversal_cz_pairs
from ftqc_patch_rotation.ir.rotation_macro import CodeBlockState
from ftqc_patch_rotation.ir.transversal import TransversalAction
from ftqc_patch_rotation.passes.se.rotated import compile_rotated_se_round, compile_rotated_fold_s_round


def initial_states(layout, count):
    return [CodeBlockState(CodeRepresentation(layout), tuple(f"{q}:d:{i}" for i in range(len(layout.data))))
            for q in range(count)]


def check_carriers(layout, q):
    return {c.id: f"{q}:a:{c.id}" for c in layout.checks}


def logical_actions(op, states):
    """Expected block-level actions. Representation changes are replayed separately."""
    if op.kind == "cz":
        qa, qb = op.qubits
        pairs = transversal_cz_pairs(states[qa].representation, states[qb].representation)
        return (TransversalAction("transversal_gate", (2*qa, 2*qb), "cz",
            pairs=tuple(((2*qa, a), (2*qb, b)) for a, b in pairs)),)
    if op.kind == "barrier":
        return (TransversalAction("barrier", tuple(2*q for q in op.qubits)),)
    q = op.qubits[0]
    state, block = states[q], 2*q
    if op.kind == "prepare_t":
        return (TransversalAction("resource_prepare", (block, block+1), gate="prepare_t"),)
    if op.kind in {"measure_t0", "measure_t1"}:
        return (TransversalAction("logical_measurement", (block,), gate="logical_measure_z",
            targets=tuple((block, i) for i in state.representation.logical_z), assumed_result=int(op.kind[-1])),)
    if op.kind == "rot":
        return (TransversalAction("deformation", (block,), deformation="rot90",
                                  permutation=state.representation.layout.zx_permutation),)
    if op.kind in ("h", "id"):
        return (TransversalAction("transversal_gate", (block,), op.kind,
            targets=tuple((block, i) for i in range(len(state.carriers_by_site)))),)
    if op.kind in ("x", "y", "z"):
        return tuple(TransversalAction("transversal_gate", (block,), basis,
            targets=tuple((block, i) for i in support))
            for basis, support in (("x", state.representation.logical_x), ("z", state.representation.logical_z))
            if op.kind in (basis, "y"))
    raise ValueError(f"unsupported transversal logical gate: {op.kind}")


def update_state(op, states):
    q = op.qubits[0] if op.qubits else None
    if op.kind == "rot":
        states[q] = states[q].rotated()
    elif op.kind == "h":
        states[q] = replace(states[q], representation=states[q].representation.toggled())
    elif op.kind == "prepare_t":
        states[q] = replace(states[q], representation=CodeRepresentation(states[q].representation.layout),
                            reset_epoch=states[q].reset_epoch+1)


def se_actions(state, q, gate, round_index, measurement_offset, *, selective_offsets=True):
    """Align selected checks first, then execute each complete verified CX layer.

    Offset changes are absolute per-check alignment targets, not atom paths.
    Fold/unfold are pairing-deformation contracts, not physical trajectories.
    The whole-block mode is retained for replaying saved v2 programs.
    """
    layout = state.representation.layout
    checks = check_carriers(layout, q)
    program = (compile_rotated_se_round(state, checks, round_index=round_index, measurement_offset=measurement_offset)
        if gate == "id" else compile_rotated_fold_s_round(state, checks, inverse=gate == "sdg",
            round_index=round_index, measurement_offset=measurement_offset))
    data, anc = 2*q, 2*q+1
    locations = {c: (data, i) for i, c in enumerate(state.carriers_by_site)}
    locations.update({c: (anc, i) for i, c in checks.items()})
    coords = {p.id: (p.x, p.y) for p in (*layout.data, *layout.checks)}
    actions, current, layer, folded = [], (0, 0), 0, False
    check_offsets = {i: (0, 0) for i in checks}
    def align(offset, layer_number, sites=None):
        nonlocal current
        if selective_offsets:
            selected = tuple(sorted(i for i in (checks if sites is None else sites)
                                    if check_offsets[i] != offset))
            if selected:
                actions.append(TransversalAction("block_offset", (anc,),
                    targets=tuple((anc, i) for i in selected), offset=offset, layer=layer_number))
                check_offsets.update((i, offset) for i in selected)
        elif current != offset:
            actions.append(TransversalAction("block_offset", (anc,), offset=offset, layer=layer_number))
            current = offset
    for instruction in program.instructions:
        if instruction.kind == "cx":
            if folded:
                actions.append(TransversalAction("deformation", (data, anc), deformation="unfold-diagonal"))
                folded = False
            layer += 1
            groups = {}
            for control, target in instruction.pairs:
                a, b = locations[control], locations[target]
                ds, cs = (a[1], b[1]) if a[0] == data else (b[1], a[1])
                offset = tuple(coords[ds][i]-coords[cs][i] for i in (0, 1))
                groups.setdefault(offset, []).append((a, b))
            if selective_offsets:
                for offset, pairs in sorted(groups.items()):
                    sites = tuple(a[1] if a[0] == anc else b[1] for a, b in pairs)
                    align(offset, layer, sites)
                actions.append(TransversalAction("transversal_gate", (data, anc), "cx",
                    pairs=tuple((locations[a], locations[b]) for a, b in instruction.pairs), layer=layer))
            else:
                while groups:
                    offset = current if current in groups else min(groups)
                    align(offset, layer)
                    actions.append(TransversalAction("transversal_gate", (data, anc), "cx",
                        pairs=tuple(groups.pop(offset)), layer=layer))
        else:
            if instruction.kind == "cz":
                align((0, 0), layer)
                actions.append(TransversalAction("deformation", (data, anc), deformation="fold-diagonal"))
                folded = True
            if instruction.kind == "measure":
                align((0, 0), layer)
            # Final ancilla H is also performed at home alignment.
            if instruction.kind == "h" and layer == 4:
                align((0, 0), layer)
            targets = tuple(locations[c] for c in instruction.targets)
            pairs = tuple((locations[a], locations[b]) for a, b in instruction.pairs)
            blocks = tuple(sorted({t[0] for t in targets} | {t[0] for p in pairs for t in p}))
            actions.append(TransversalAction("transversal_gate", blocks, instruction.kind,
                                             targets=targets, pairs=pairs))
    assert current == (0, 0) and all(o == (0, 0) for o in check_offsets.values()) and not folded
    readouts = tuple((r.record_index, r.check_id, r.basis) for r in program.measurements)
    return tuple(actions), readouts
