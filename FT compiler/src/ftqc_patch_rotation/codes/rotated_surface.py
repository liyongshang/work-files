"""Odd-distance rotated CSS code in doubled lattice coordinates.

Coordinates describe topology, not processor traps. Data IDs are row-major;
the ZX permutation maps a source data ID to its destination after (x,y)->(2d-y,x).
The four interaction layers describe a conventional syndrome circuit, not
an AOD motion program or a policy for inserting correction rounds.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CodeData:
    id: int
    x: int
    y: int


@dataclass(frozen=True)
class CodeCheck:
    id: int
    x: int
    y: int
    basis: str
    support: tuple[int, ...]


def _mask(support):
    return sum(1 << q for q in support)


def _rank(rows):
    pivots = {}
    for row in rows:
        while row:
            pivot = row.bit_length() - 1
            if pivot not in pivots:
                pivots[pivot] = row
                break
            row ^= pivots[pivot]
    return len(pivots)


@dataclass(frozen=True)
class RotatedSurfaceLayout:
    distance: int
    data: tuple[CodeData, ...]
    checks: tuple[CodeCheck, ...]
    logical_x: tuple[int, ...]
    logical_z: tuple[int, ...]
    zx_permutation: tuple[int, ...]
    # Each pair is (control ID, target ID). Check IDs follow all data IDs.
    interaction_layers: tuple[tuple[tuple[int, int], ...], ...]
    code_kind: str = "rotated_surface"
    convention: str = "rotated-css-v1"

    def validate(self):
        """Check CSS rank, logical operators, ZX duality and layer coverage."""
        n = len(self.data)
        if n != self.distance**2 or tuple(q.id for q in self.data) != tuple(range(n)):
            raise ValueError("invalid data indexing")
        if len(self.checks) != n - 1 or {c.id for c in self.checks} != set(range(n, 2*n-1)):
            raise ValueError("invalid check indexing")
        if any(c.basis not in ("X", "Z") or len(c.support) not in (2, 4)
               or len(set(c.support)) != len(c.support)
               or not set(c.support) <= set(range(n)) for c in self.checks):
            raise ValueError("invalid check support")
        rows = {b: [_mask(c.support) for c in self.checks if c.basis == b] for b in ("X", "Z")}
        if any((x & z).bit_count() % 2 for x in rows["X"] for z in rows["Z"]):
            raise ValueError("noncommuting CSS checks")
        if sum(_rank(r) for r in rows.values()) != n - 1:
            raise ValueError("code must encode one logical qubit")
        logical = {"X": _mask(self.logical_x), "Z": _mask(self.logical_z)}
        for b, opposite in (("X", "Z"), ("Z", "X")):
            support = self.logical_x if b == "X" else self.logical_z
            if len(set(support)) != self.distance or not set(support) <= set(range(n)):
                raise ValueError("invalid logical support")
            if any((logical[b] & r).bit_count() % 2 for r in rows[opposite]):
                raise ValueError("logical operator anticommutes with checks")
            if _rank(rows[b] + [logical[b]]) == _rank(rows[b]):
                raise ValueError("logical operator is a stabilizer")
        if (logical["X"] & logical["Z"]).bit_count() % 2 != 1:
            raise ValueError("logical X and Z must anticommute")
        if sorted(self.zx_permutation) != list(range(n)):
            raise ValueError("ZX mapping must be a permutation")
        for b, opposite in (("X", "Z"), ("Z", "X")):
            transformed = {_mask(tuple(self.zx_permutation[q] for q in c.support))
                           for c in self.checks if c.basis == b}
            if transformed != set(rows[opposite]):
                raise ValueError("permutation does not exchange X/Z checks")
            support = self.logical_x if b == "X" else self.logical_z
            difference = _mask(tuple(self.zx_permutation[q] for q in support)) ^ logical[opposite]
            if _rank(rows[opposite] + [difference]) != _rank(rows[opposite]):
                raise ValueError("permutation does not exchange logical X/Z modulo checks")
        expected = {(c.id, q) if c.basis == "X" else (q, c.id)
                    for c in self.checks for q in c.support}
        flattened = [pair for layer in self.interaction_layers for pair in layer]
        if len(self.interaction_layers) != 4 or len(flattened) != len(expected) or set(flattened) != expected:
            raise ValueError("incorrect syndrome interaction coverage")
        for layer in self.interaction_layers:
            operands = [q for pair in layer for q in pair]
            if len(operands) != len(set(operands)):
                raise ValueError("syndrome layer reuses an operand")


def rotated_surface_layout(distance: int) -> RotatedSurfaceLayout:
    """Build the first backend's topology for odd integer d >= 3."""
    if isinstance(distance, bool) or not isinstance(distance, int) or distance < 3 or distance % 2 == 0:
        raise ValueError("rotated surface code requires odd integer distance >= 3")
    d = distance
    data = tuple(CodeData(r*d+c, 2*c+1, 2*r+1) for r in range(d) for c in range(d))
    lookup = {(q.x, q.y): q.id for q in data}
    checks = []
    for y in range(0, 2*d+1, 2):
        for x in range(0, 2*d+1, 2):
            basis = "X" if (x+y) % 4 == 2 else "Z"
            if (x in (0, 2*d) and basis == "X") or (y in (0, 2*d) and basis == "Z"):
                continue
            support = tuple(sorted(lookup[x+dx, y+dy] for dx in (-1, 1) for dy in (-1, 1)
                                   if (x+dx, y+dy) in lookup))
            if len(support) in (2, 4):
                checks.append(CodeCheck(d*d+len(checks), x, y, basis, support))
    offsets = {"X": ((1, 1), (-1, 1), (1, -1), (-1, -1)),
               "Z": ((1, 1), (1, -1), (-1, 1), (-1, -1))}
    layers = []
    for layer in range(4):
        pairs = []
        for check in checks:
            dx, dy = offsets[check.basis][layer]
            q = lookup.get((check.x+dx, check.y+dy))
            if q is not None:
                pairs.append((check.id, q) if check.basis == "X" else (q, check.id))
        layers.append(tuple(pairs))
    result = RotatedSurfaceLayout(d, data, tuple(checks),
        tuple(q.id for q in data if q.x == 1), tuple(q.id for q in data if q.y == 1),
        tuple(lookup[2*d-q.y, q.x] for q in data), tuple(layers))
    result.validate()
    return result
