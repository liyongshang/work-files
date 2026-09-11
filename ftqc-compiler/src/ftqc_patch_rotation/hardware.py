"""Exact-coordinate processor geometry; all distances are in micrometres."""
from dataclasses import asdict, dataclass
from fractions import Fraction


def exact(value):
    return Fraction(str(value))


@dataclass(frozen=True)
class ProcessorConfig:
    d: int
    a1: int
    b1: int
    a2: int
    b2: int
    s: float = 5.0
    pair_pitch_x: float | None = None
    pair_pitch_y: float | None = None
    pair_offset: float | None = None
    gap_se: float | None = None
    gap_em: float | None = None
    L: float | None = None
    H: float | None = None


@dataclass(frozen=True)
class Patch:
    id: str
    zone: str
    row: int
    col: int
    x: Fraction
    y: Fraction
    pair: str | None = None
    member: int | None = None


class Processor:
    def __init__(self, config: ProcessorConfig):
        self.config = config
        for name in ("d", "a1", "b1", "a2", "b2"):
            value = getattr(config, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        s = exact(config.s)
        self.s = s
        self.px = exact(config.pair_pitch_x) if config.pair_pitch_x is not None else 2*s
        self.py = exact(config.pair_pitch_y) if config.pair_pitch_y is not None else 2*s
        delta = exact(config.pair_offset) if config.pair_offset is not None else s/5
        gse = exact(config.gap_se) if config.gap_se is not None else 2*s
        gem = exact(config.gap_em) if config.gap_em is not None else 2*s
        if min(s, self.px, self.py, delta) <= 0 or delta >= self.px:
            raise ValueError("invalid site pitch or intra-pair offset")
        if min(gse, gem) <= 0:
            raise ValueError("zone gaps must separate the outermost site rows")
        d = config.d
        wsm, hsm = (config.b1*d-1)*s, (config.a1*d-1)*s
        went, hent = (config.a2*d-1)*self.px+delta, (config.b2*d-1)*self.py
        height = 2*hsm+gse+hent+gem
        self.L = exact(config.L) if config.L is not None else max(wsm, went)
        self.H = exact(config.H) if config.H is not None else height
        if self.L < max(wsm, went) or self.H != height:
            raise ValueError("L cannot contain the arrays, or H disagrees with pitches/gaps")
        self.patches = {}
        self.pairs = {}
        for zone, ybase in (("storage", Fraction(0)), ("measurement", hsm+gse+hent+gem)):
            for row in range(config.a1):
                for col in range(config.b1):
                    key = f"{zone}:{row}:{col}"
                    self.patches[key] = Patch(key, zone, row, col, col*d*s, ybase+row*d*s)
        for row in range(config.b2):
            for col in range(config.a2):
                pair = f"pair:{row}:{col}"
                members = []
                for member in range(2):
                    key = f"entanglement:{row}:{col}:{member}"
                    members.append(key)
                    self.patches[key] = Patch(key, "entanglement", row, 2*col+member,
                        col*d*self.px+member*delta, hsm+gse+row*d*self.py, pair, member)
                self.pairs[pair] = tuple(members)
        ordered = sorted(self.patches.values(), key=lambda p: (p.row, p.col))
        split = config.a1-config.a1//2
        self.data_patches = tuple(p.id for p in ordered if p.zone == "storage" and p.row >= split)
        self.ancilla_patches = tuple(p.id for p in ordered if p.zone == "storage" and p.row < split)

    @property
    def pair_count(self):
        return len(self.pairs)

    def patch_anchor(self, patch_id):
        p = self.patches[patch_id]
        return p.x, p.y

    def zone_of(self, patch_id):
        return self.patches[patch_id].zone

    def pair_of(self, patch_id):
        return self.patches[patch_id].pair

    def pair_members(self, pair_id):
        return self.pairs[pair_id]

    def site_position(self, site_id):
        """Site ID is (patch_id, local_row, local_col)."""
        patch, row, col = site_id
        if not (0 <= row < self.config.d and 0 <= col < self.config.d):
            raise ValueError("site index out of range")
        x, y = self.patch_anchor(patch)
        dx, dy = (self.px, self.py) if self.zone_of(patch) == "entanglement" else (self.s, self.s)
        return x+col*dx, y+row*dy

    def patch_sites(self, patch_id):
        return tuple((patch_id, r, c) for r in range(self.config.d) for c in range(self.config.d))

    def distance2(self, a, b):
        x, y = self.patch_anchor(a)
        u, v = self.patch_anchor(b)
        return (x-u)**2+(y-v)**2

    def to_dict(self):
        return {"config": asdict(self.config), "L": str(self.L), "H": str(self.H),
                "patches": [{**asdict(p), "x": str(p.x), "y": str(p.y)} for p in self.patches.values()]}
