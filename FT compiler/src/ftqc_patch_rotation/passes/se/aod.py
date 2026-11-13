"""Cartesian-product pickup and exact endpoint checks for rigid AOD moves.

Continuous trajectories, clearance and trap/laser dynamics are not modeled.
"""
from dataclasses import replace


def pickup_grid(state, atom_ids):
    if not atom_ids or len(set(atom_ids)) != len(atom_ids):
        raise ValueError("AOD selection must be nonempty and unique")
    if not set(atom_ids) <= state.atoms.keys():
        raise ValueError("AOD selection contains an unknown atom")
    xs = {state.atoms[q].x for q in atom_ids}
    ys = {state.atoms[q].y for q in atom_ids}
    caught = {a.id for a in state.atoms.values() if a.x in xs and a.y in ys}
    return xs, ys, caught


def apply_aod(state, op):
    _, _, caught = pickup_grid(state, op.atoms)
    if caught != set(op.atoms):
        raise ValueError(f"AOD grid also picks up unintended atoms: {sorted(caught-set(op.atoms))}")
    if len(op.delta) != 2 or op.delta == (0, 0):
        raise ValueError("AOD move requires a nonzero 2D translation")
    updated = state.atoms.copy()
    dx, dy = op.delta
    for q in op.atoms:
        a = updated[q]
        updated[q] = replace(a, x=a.x+dx, y=a.y+dy)
    if len({(a.x, a.y) for a in updated.values()}) != len(updated):
        raise ValueError("AOD endpoint overlaps a stationary atom")
    state.atoms = updated
