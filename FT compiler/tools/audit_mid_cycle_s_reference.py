"""Compare the author's SE ordering with our current topology convention.

Read only the author's layout class; do not invoke its file-writing circuit
generator or decoder. A coordinate rotation aligns end-cycle CSS checks but
does not assume equivalence of their half-cycle states.
"""
import importlib.util
import json
from pathlib import Path

from ftqc_patch_rotation.codes import CodeRepresentation, rotated_surface_layout


def audit(distance, reference_module, orientation=False):
    ours = rotated_surface_layout(distance)
    representation = CodeRepresentation(ours, orientation)
    reference = reference_module.Rotated_surface_code(distance)
    d = distance

    def position(qubit):
        x, y = qubit.pos
        if orientation:
            return int(2*d-2*x-1), int(2*d-2*y-1)
        return int(2*y+1), int(2*d-2*x-1)

    our_positions = {q.id: (q.x, q.y) for q in (*ours.data, *ours.checks)}
    reference_checks = []
    reference_layers = [set() for _ in range(4)]
    for basis, checks, directions in (
            ("X", reference.x_check_collection, ("nw", "sw", "ne", "se")),
            ("Z", reference.z_check_collection, ("nw", "ne", "sw", "se"))):
        for check in checks:
            support = frozenset(position(q) for q in check.neighbor.values() if q is not None)
            reference_checks.append((position(check), basis, support))
            for i, direction in enumerate(directions):
                q = check.neighbor[direction]
                if q is not None:
                    pair = (position(check), position(q)) if basis == "X" else (position(q), position(check))
                    reference_layers[i].add(pair)
    current_checks = {(our_positions[c.id], c.basis, frozenset(our_positions[q] for q in c.support))
                      for c in representation.checks}
    current_layers = [{(our_positions[t], our_positions[c]) if orientation else (our_positions[c], our_positions[t])
                       for c, t in layer}
                      for layer in ours.interaction_layers]
    if current_checks != set(reference_checks):
        raise ValueError("coordinate mapping does not align the end-cycle CSS checks")
    if set.union(*current_layers) != set.union(*reference_layers):
        raise ValueError("full-round interaction sets differ")
    return {"distance": d, "orientation": orientation, "end_cycle_checks_match": True, "full_round_pairs_match": True,
            "layer_pairs_match": [a == b for a, b in zip(current_layers, reference_layers)],
            "layer_symmetric_difference_sizes": [len(a ^ b) for a, b in zip(current_layers, reference_layers)],
            "first_two_layers_pair_set_match": set.union(*current_layers[:2]) == set.union(*reference_layers[:2]),
            "coordinate_map": ("project (x,y) = (2*d-2*paper_x-1, 2*d-2*paper_y-1)" if orientation else
                               "project (x,y) = (2*paper_y+1, 2*d-2*paper_x-1)"),
            "scope": "Pair ordering comparison only; no mid-cycle S correctness or detector certificate."}


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / "external/dynamical-s-gate/surface_codes.py"
    spec = importlib.util.spec_from_file_location("author_surface_codes", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = {"reference_commit": "c3b7a1e2f95d49a5853d5534a4596854317890e9",
              "cases": [audit(d, module, o) for d in (3, 5, 7) for o in (False, True)]}
    output = root / "outputs/protocol_audit/mid_cycle_s_ordering.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
