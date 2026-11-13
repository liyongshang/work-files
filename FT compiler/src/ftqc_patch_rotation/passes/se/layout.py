"""Non-rotated surface-code occupancy on a (2d-1) by (2d-1) site grid."""
from ftqc_patch_rotation.ir.se import SEAtom, SEState


def check_patch_pair(processor, data_patch, ancilla_patch):
    if data_patch == ancilla_patch:
        raise ValueError("DQ and AQ require distinct patches")
    for patch in (data_patch, ancilla_patch):
        if patch not in processor.patches or processor.zone_of(patch) != "entanglement":
            raise ValueError("DQ and AQ must be in the entanglement zone")
    if processor.pair_of(data_patch) != processor.pair_of(ancilla_patch):
        raise ValueError("DQ and AQ must occupy the same entanglement patch pair")
    if processor.config.d < 2 or processor.site_grid_size != 2 * processor.config.d - 1:
        raise ValueError("non-rotated SE requires d >= 2 and site_grid_size = 2*d-1")


def make_se_state(processor, data_patch, ancilla_patch):
    check_patch_pair(processor, data_patch, ancilla_patch)
    atoms = {}
    for role, patch, parity in (("D", data_patch, 0), ("A", ancilla_patch, 1)):
        for _, row, col in processor.patch_sites(patch):
            if (row + col) % 2 == parity:
                key = f"{role}{row + 1}_{col + 1}"
                x, y = processor.site_position((patch, row, col))
                atoms[key] = SEAtom(key, role, x, y)
    return SEState(atoms, data_patch, ancilla_patch)


def occupied_slots(processor, state, role):
    patch = state.data_patch if role == "D" else state.ancilla_patch
    lookup = {processor.site_position(site): site[1:] for site in processor.patch_sites(patch)}
    result = {}
    for atom in state.atoms.values():
        if atom.role == role:
            slot = lookup.get((atom.x, atom.y))
            if slot is None or slot in result:
                raise ValueError(f"{atom.id} is not uniquely restored to its home patch")
            result[slot] = atom.id
    return result


def validate_restored(processor, state):
    check_patch_pair(processor, state.data_patch, state.ancilla_patch)
    if any(a.role not in ("D", "A") or key != a.id for key, a in state.atoms.items()):
        raise ValueError("invalid atom identity or role")
    if len({(a.x, a.y) for a in state.atoms.values()}) != len(state.atoms):
        raise ValueError("overlapping atoms")
    n = processor.site_grid_size
    for role, parity in (("D", 0), ("A", 1)):
        expected = {(r, c) for r in range(n) for c in range(n) if (r+c) % 2 == parity}
        if set(occupied_slots(processor, state, role)) != expected:
            raise ValueError(f"incorrect {role} checkerboard occupancy")
