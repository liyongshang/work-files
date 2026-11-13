"""Resolve LRUD neighbors and the two/three-move restoration strategy."""
from dataclasses import dataclass

from ftqc_patch_rotation.ir.se import SEInstruction
from .layout import occupied_slots, validate_restored


DIRECTIONS = {"L": (0, -1), "R": (0, 1), "U": (-1, 0), "D": (1, 0)}


@dataclass(frozen=True)
class SELayer:
    direction: str
    swap: bool
    instructions: tuple[SEInstruction, ...]


def plan_layer(processor, state, direction, swap=False):
    validate_restored(processor, state)
    if direction not in DIRECTIONS:
        raise ValueError("SE direction must be L, R, U or D")
    dr, dc = DIRECTIONS[direction]
    data, anc = occupied_slots(processor, state, "D"), occupied_slots(processor, state, "A")
    pairs = tuple((data[r+dr, c+dc], q) for (r, c), q in sorted(anc.items())
                  if (r+dr, c+dc) in data)
    paired_d, paired_a = tuple(p[0] for p in pairs), tuple(p[1] for p in pairs)
    shift = (dc*processor.px, dr*processor.py)
    inverse = tuple(-v for v in shift)
    ops = [SEInstruction("aod", direction, "approach", paired_a, shift),
           SEInstruction("entangle", direction, "entangle", pairs=pairs)]
    if swap:
        ops.append(SEInstruction("roles", direction, "exchange_roles_and_homes", pairs=pairs))
        ops.append(SEInstruction("aod", direction, "restore_paired_old_D", paired_d, inverse))
        dxy, axy = processor.patch_anchor(state.data_patch), processor.patch_anchor(state.ancilla_patch)
        offset = tuple(a-d for a, d in zip(axy, dxy))
        boundary_d = tuple(q for q in data.values() if q not in paired_d)
        boundary_a = tuple(q for q in anc.values() if q not in paired_a)
        ops.append(SEInstruction("aod", direction, "transfer_boundary_old_D", boundary_d, offset))
        ops.append(SEInstruction("aod", direction, "transfer_boundary_old_A", boundary_a,
                                 tuple(-v for v in offset)))
    else:
        # The moved strip nearest the stationary boundary shares one coordinate
        # with it. Restore all farther strips first, then only that single strip.
        axis = 1 if dc else 0
        sign = dc or dr
        near_index = 1 if sign < 0 else processor.site_grid_size-2
        near = tuple(q for slot, q in anc.items() if q in paired_a and slot[axis] == near_index)
        far = tuple(q for slot, q in anc.items() if q in paired_a and slot[axis] != near_index)
        if far:
            ops.append(SEInstruction("aod", direction, "restore_far_strips", far, inverse))
        ops.append(SEInstruction("aod", direction, "restore_near_strip", near, inverse))
    return SELayer(direction, swap, tuple(ops))
