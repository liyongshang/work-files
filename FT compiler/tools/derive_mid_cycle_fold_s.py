"""Research audit of diagonal fold candidates, not production gate lowering."""
import json
from pathlib import Path

import stim

from ftqc_patch_rotation import CodeBlockState, compile_rotated_se_round
from ftqc_patch_rotation.codes import CodeRepresentation, rotated_surface_layout


def bell_input(rep):
    n = len(rep.layout.data)
    width = 2*n
    reference = width-1
    generators = []
    for c in rep.checks:
        p = stim.PauliString(width)
        for q in c.support:
            p[q] = c.basis
        generators.append(p)
    for q in range(n, reference):
        p = stim.PauliString(width)
        p[q] = "Z"
        generators.append(p)
    x, z = stim.PauliString(width), stim.PauliString(width)
    for q in rep.logical_x:
        x[q] = "X"
    for q in rep.logical_z:
        z[q] = "Z"
    xx, zz = x.copy(), z.copy()
    xx[reference], zz[reference] = "X", "Z"
    sim = stim.TableauSimulator()
    sim.set_inverse_tableau(stim.Tableau.from_stabilizers(generators+[xx, zz]).inverse())
    yx = 1j*x*z
    yx[reference] = "X"
    return sim, yx, zz


def candidate(rep, axis, inverse=False):
    layout = rep.layout
    n = len(layout.data)
    state = CodeBlockState(rep, tuple(f"d{i}" for i in range(n)))
    program = compile_rotated_se_round(state, {c.id: f"a{c.id}" for c in layout.checks})
    carrier_wires = dict(zip(state.carriers_by_site+program.check_carriers, range(2*n-1)))
    positions = {(q.x, q.y): q.id for q in (*layout.data, *layout.checks)}
    bulk = {xy: q for xy, q in positions.items() if all(1 <= v <= 2*layout.distance-1 for v in xy)}
    fold = stim.Circuit()
    pairs, data_diagonal, check_diagonal = [], [], []
    for (x, y), q in sorted(bulk.items()):
        mirror = (y, x) if axis == "diagonal" else (2*layout.distance-y, 2*layout.distance-x)
        if (x, y) == mirror:
            (data_diagonal if q < n else check_diagonal).append(q)
        elif (x, y) < mirror:
            pairs.extend((q, bulk[mirror]))
    if pairs:
        fold.append("CZ", pairs)
    fold.append("S_DAG" if inverse else "S", data_diagonal)
    fold.append("S" if inverse else "S_DAG", check_diagonal)
    circuit = stim.Circuit()
    unitary = stim.Circuit()
    layers = 0
    for op in program.instructions:
        name = {"reset": "R", "h": "H", "cx": "CX", "measure": "M"}[op.kind]
        targets = [carrier_wires[q] for pair in op.pairs for q in pair] if op.kind == "cx" else [carrier_wires[q] for q in op.targets]
        circuit.append(name, targets)
        if op.kind not in ("reset", "measure"):
            unitary.append(name, targets)
        if op.kind == "cx":
            layers += 1
            if layers == 2:
                circuit += fold
                unitary += fold
    return circuit, unitary, program.to_stim()


def coefficients(pauli, generators, basis=None):
    """Solve the binary symplectic span, retaining generator coefficients."""
    def bits(p):
        xs, zs = p.to_numpy()
        return sum((int(x) << i) | (int(z) << (i+len(p))) for i, (x, z) in enumerate(zip(xs, zs)))
    if basis is None:
        basis = {}
    if not basis:
        for i, p in enumerate(generators):
            row, label = bits(p), 1 << i
            while row:
                pivot = row.bit_length()-1
                if pivot not in basis:
                    basis[pivot] = row, label
                    break
                r, l = basis[pivot]
                row, label = row ^ r, label ^ l
    row, label = bits(pauli), 0
    while row:
        pivot = row.bit_length()-1
        if pivot not in basis:
            return None
        r, l = basis[pivot]
        row, label = row ^ r, label ^ l
    return [i for i in range(len(generators)) if label >> i & 1]


def signed_member(pauli, generators, basis=None):
    selection = coefficients(pauli, generators, basis)
    if selection is None:
        return False
    product = stim.PauliString(len(pauli))
    for i in selection:
        product *= generators[i]
    return product == pauli


def certificate(rep, unitary, inverse_gate):
    n = len(rep.layout.data)
    width = 2*n-1
    generators = []
    checks = []
    for check in rep.checks:
        p = stim.PauliString(width)
        for q in check.support:
            p[q] = check.basis
        generators.append(p)
        checks.append(p)
    measured = []
    for q in range(n, width):
        p = stim.PauliString(width)
        p[q] = "Z"
        generators.append(p)
        measured.append(p)
    x, z = stim.PauliString(width), stim.PauliString(width)
    for q in rep.logical_x:
        x[q] = "X"
    for q in rep.logical_z:
        z[q] = "Z"
    y = 1j*x*z
    tableau = unitary.to_tableau()
    back = tableau.inverse()
    expected_y = -y if inverse_gate else y
    input_basis, output_basis = {}, {}
    logical_s = signed_member(back(expected_y)*x, generators, input_basis)
    logical_z = signed_member(back(z)*z, generators, input_basis)
    output_generators = [tableau(p) for p in generators]
    relations = []
    for p in checks:
        selection = coefficients(p, output_generators+measured, output_basis)
        if selection is None:
            relations.append(None)
            continue
        product = stim.PauliString(width)
        for i in selection:
            product *= (output_generators+measured)[i]
        if product != p and product != -p:
            raise ValueError("non-real stabilizer relation")
        relations.append({"sign": 1 if product == p else -1,
                          "measurement_indices": [i-len(output_generators) for i in selection if i >= len(output_generators)]})
    return {"logical_X_to_signed_Y": logical_s, "logical_Z_fixed": logical_z,
            "logical_maps_exact_without_stabilizer_factors": back(expected_y) == x and back(z) == z,
            "all_output_checks_determined_by_measurements": all(r is not None for r in relations),
            "all_output_checks_plus_one_before_measurement": all(
                r is not None and r["sign"] == 1 and not r["measurement_indices"] for r in relations),
            "output_check_relations": relations,
            "scope": "Exact signed Clifford/subspace certificate for this distance; no noise/detector-distance certificate."}


def half_turn_certificate(distance):
    layout = rotated_surface_layout(distance)
    p = layout.zx_permutation
    half_turn = tuple(p[p[q]] for q in range(distance*distance))
    checks = {(c.basis, frozenset(c.support)) for c in layout.checks}
    mapped_checks = {(c.basis, frozenset(half_turn[q] for q in c.support)) for c in layout.checks}
    logical_preserved = []
    for basis, support in (("X", layout.logical_x), ("Z", layout.logical_z)):
        generators = []
        for c in layout.checks:
            if c.basis == basis:
                row = stim.PauliString(distance*distance)
                for q in c.support:
                    row[q] = basis
                generators.append(row)
        difference = stim.PauliString(distance*distance)
        for q in set(support) ^ {half_turn[q] for q in support}:
            difference[q] = basis
        logical_preserved.append(signed_member(difference, generators))
    return {"d": distance, "checks_preserved": checks == mapped_checks,
            "logical_X_Z_preserved_modulo_stabilizers": logical_preserved,
            "carrier_permutation_is_identity": all(q == t for q, t in enumerate(half_turn)),
            "orientation_from_false": [False, True, False]}


def audit(d, orientation, axis, inverse):
    rep = CodeRepresentation(rotated_surface_layout(d), orientation)
    circuit, unitary, following = candidate(rep, axis, inverse)
    sim, yx, zz = bell_input(rep)
    sim.do_circuit(circuit)
    first = [sim.peek_observable_expectation(yx), sim.peek_observable_expectation(zz)]
    sim.do_circuit(following)
    second = [sim.peek_observable_expectation(yx), sim.peek_observable_expectation(zz)]
    return {"d": d, "orientation": orientation, "axis": axis, "inverse": inverse,
            "S_round_YX_ZZ": first, "following_I_round_YX_ZZ": second,
            "certificate": certificate(rep, unitary, inverse)}


def main():
    cases = [audit(d, o, axis, inv) for d in (3, 5, 7, 9) for o in (False, True)
             for axis in ("diagonal", "antidiagonal") for inv in (False, True)]
    root = Path(__file__).resolve().parents[1]
    folder = root / "outputs/protocol_audit"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fold_s_candidates.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    rotations = [half_turn_certificate(d) for d in (3, 5, 7, 9)]
    (folder / "half_turn_certificates.json").write_text(json.dumps(rotations, indent=2), encoding="utf-8")
    for c in cases:
        print({k: v for k, v in c.items() if k != "certificate"},
              {k: v for k, v in c["certificate"].items() if k != "output_check_relations"})
    print("Half-turn certificates:", rotations)


if __name__ == "__main__":
    main()
