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
    site_grid_size: int | None = None
    code_kind: str = "unrotated_surface"
    geometry_model: str | None = None
    num_y_road: int = 1
    storage_num_x_road: int = 1
    entanglement_num_x_road: int = 1

    def __post_init__(self):
        if self.geometry_model is None:
            object.__setattr__(self, "geometry_model", "vertical_roads" if self.code_kind == "rotated_surface" else "legacy")
        if self.geometry_model not in {"legacy", "vertical_roads"}:
            raise ValueError("unsupported geometry model")
        for name in ("num_y_road", "storage_num_x_road", "entanglement_num_x_road"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.code_kind not in ("unrotated_surface", "rotated_surface"):
            raise ValueError("unsupported processor code kind")
        if self.code_kind == "rotated_surface":
            if type(self.d) is not int or self.d < 3 or self.d % 2 == 0:
                raise ValueError("rotated surface code requires odd d >= 3")
            if self.site_grid_size is not None and (type(self.site_grid_size) is not int or self.site_grid_size < 2*self.d+3):
                raise ValueError("rotated patch side must be an integer >= 2d+3")
        if self.site_grid_size is None:
            object.__setattr__(self, "site_grid_size", 2*self.d+3 if self.code_kind == "rotated_surface" else 2*self.d-1)


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
        self.has_roads = config.geometry_model == "vertical_roads"
        default_pitch = s if self.has_roads else 2*s
        self.px = exact(config.pair_pitch_x) if config.pair_pitch_x is not None else default_pitch
        self.py = exact(config.pair_pitch_y) if config.pair_pitch_y is not None else default_pitch
        if self.has_roads and (self.px != s or self.py != s):
            raise ValueError("vertical road geometry requires entanglement and SLM site pitches to match")
        delta = exact(config.pair_offset) if config.pair_offset is not None else s/5
        gse = exact(config.gap_se) if config.gap_se is not None else 2*s
        gem = exact(config.gap_em) if config.gap_em is not None else 2*s
        if min(s, self.px, self.py, delta) <= 0 or delta >= self.px:
            raise ValueError("invalid site pitch or intra-pair offset")
        self.pair_offset = delta
        if min(gse, gem) <= 0:
            raise ValueError("zone gaps must separate the outermost site rows")
        d = config.site_grid_size
        if type(d) is not int or d <= 0:
            raise ValueError("site_grid_size must be a positive integer")
        self.site_grid_size = d
        wsm, hsm = (config.b1*d-1)*s, (config.a1*d-1)*s
        went = (config.a2*d-1)*self.px + (0 if self.has_roads else delta)
        hent = (config.b2*d-1)*self.py + (delta if self.has_roads else 0)
        height = 2*hsm+gse+hent+gem
        width = max(wsm, went) + (s*config.num_y_road/(config.num_y_road+1) if self.has_roads else 0)
        height += s*config.storage_num_x_road/(config.storage_num_x_road+1) if self.has_roads else 0
        self.L = exact(config.L) if config.L is not None else width
        self.H = exact(config.H) if config.H is not None else height
        if self.L < width or self.H != height:
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
                    self.patches[key] = Patch(key, "entanglement",
                        2*row+member if self.has_roads else row, col if self.has_roads else 2*col+member,
                        col*d*self.px+(0 if self.has_roads else member*delta),
                        hsm+gse+row*d*self.py+(member*delta if self.has_roads else 0), pair, member)
                self.pairs[pair] = tuple(members)
        ordered = sorted(self.patches.values(), key=lambda p: (p.row, p.col))
        split = config.a1-config.a1//2
        self.data_patches = tuple(p.id for p in ordered if p.zone == "storage" and p.row >= split)
        self.ancilla_patches = tuple(p.id for p in ordered if p.zone == "storage" and p.row < split)
        if config.code_kind == "rotated_surface":
            # Each logical code occupies one storage patch, with disjoint data
            # and check sites. The two block selectors share the same home.
            storage = tuple(p.id for p in ordered if p.zone == "storage")
            self.data_patches = self.ancilla_patches = storage

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
        if not (0 <= row < self.site_grid_size and 0 <= col < self.site_grid_size):
            raise ValueError("site index out of range")
        x, y = self.patch_anchor(patch)
        dx, dy = (self.px, self.py) if self.zone_of(patch) == "entanglement" else (self.s, self.s)
        return x+col*dx, y+row*dy

    def patch_sites(self, patch_id):
        return tuple((patch_id, r, c) for r in range(self.site_grid_size) for c in range(self.site_grid_size))

    def distance2(self, a, b):
        x, y = self.patch_anchor(a)
        u, v = self.patch_anchor(b)
        return (x-u)**2+(y-v)**2

    def to_dict(self):
        result = {"config": asdict(self.config), "L": str(self.L), "H": str(self.H),
                  "patches": [{**asdict(p), "x": str(p.x), "y": str(p.y)} for p in self.patches.values()]}
        if self.has_roads:
            from ftqc_patch_rotation.roads import SiteRoads
            result["roads"] = SiteRoads(self).to_dict()
        return result
