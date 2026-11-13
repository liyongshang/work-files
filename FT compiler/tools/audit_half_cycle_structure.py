"""Signed comparison to the standard unrotated patch in fixed coordinates.

This does not classify codes under arbitrary Clifford transformations or
alternative embeddings. Run with the optional code-validation dependency.
"""
import json
from pathlib import Path

import stim

from derive_mid_cycle_fold_s import signed_member
from ftqc_patch_rotation.codes import rotated_surface_layout


def audit(distance, mode="original"):
    layout = rotated_surface_layout(distance)
    width = 2*distance*distance-1
    coords = {(q.x, q.y): q.id for q in (*layout.data, *layout.checks)}
    initial = []  # after X-ancilla preparation, before the first CX layer
    for check in layout.checks:
        p = stim.PauliString(width)
        for q in check.support:
            p[q] = check.basis
        initial.append(p)
    for check in layout.checks:
        p = stim.PauliString(width)
        p[check.id] = check.basis
        initial.append(p)
    circuit = stim.Circuit()
    circuit.append("I", [width-1])  # include untouched outer ancillas
    for i in range(2):
        if mode == "original":
            pairs = layout.interaction_layers[i]
        else:
            offsets = {"common-horizontal": (-1, 1), "common-vertical": (1, -1),
                       "common-opposite": (-1, -1), "common-repeat": (1, 1)}
            if mode not in offsets:
                raise ValueError("unknown comparison mode")
            off = (1, 1) if i == 0 else offsets[mode]
            pairs = []
            for check in layout.checks:
                data = coords.get((check.x+off[0], check.y+off[1]))
                if data is not None:
                    pairs.append((check.id, data) if check.basis == "X" else (data, check.id))
        circuit.append("CX", [q for pair in pairs for q in pair])
    tableau = circuit.to_tableau()
    actual = [tableau(p) for p in initial]
    targets = []
    # Active qubits: odd/odd data plus internal even/even ancillas.
    # X centers even/odd, Z centers odd/even; boundary crosses have weight 3.
    for x in range(1, 2*distance):
        for y in range(1, 2*distance):
            if (x+y) % 2 == 0:
                continue
            p = stim.PauliString(width)
            basis = "X" if x % 2 == 0 else "Z"
            for xy in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                if xy in coords and all(1 <= v <= 2*distance-1 for v in xy):
                    p[coords[xy]] = basis
            targets.append((f"{basis}-cross@{x},{y}", p))
    for check in layout.checks:
        if 1 <= check.x <= 2*distance-1 and 1 <= check.y <= 2*distance-1:
            continue
        p = stim.PauliString(width)
        p[check.id] = check.basis
        targets.append((f"decoupled-{check.basis}@{check.x},{check.y}", p))
    assert len(targets) == width-1
    forward_basis, backward_basis = {}, {}
    missing = [label for label, p in targets if not signed_member(p, actual, forward_basis)]
    target_rows = [p for _, p in targets]
    reverse = all(signed_member(p, target_rows, backward_basis) for p in actual)
    return {"distance": distance, "mode": mode,
            "active_patch_qubits": distance*distance+(distance-1)**2,
            "cross_checks": 2*distance*(distance-1),
            "decoupled_outer_ancillas": 2*(distance-1),
            "same_signed_stabilizer_group": not missing and reverse,
            "missing_target_generators": missing,
            "scope": "Fixed coordinates and carrier labels; no classification under other embeddings."}


def main():
    reports = [audit(d, mode) for d in (3, 5, 7, 9)
               for mode in ("original", "common-horizontal", "common-vertical", "common-opposite", "common-repeat")]
    path = Path(__file__).resolve().parents[1] / "outputs/protocol_audit/half_cycle_structure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    for report in reports:
        print(report["distance"], report["mode"], report["same_signed_stabilizer_group"],
              len(report["missing_target_generators"]))


if __name__ == "__main__":
    main()
