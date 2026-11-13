"""Explicit patch buses over the existing three-zone processor geometry.

Bus edges describe permitted patch transfers, not atom trajectories. Logical
bus row numbering is independent of the legacy physical patch identifiers.
"""
from dataclasses import asdict, dataclass

from ftqc_patch_rotation.hardware import Processor


@dataclass(frozen=True)
class BusNode:
    patch_id: str
    zone: str  # lower, upper, entanglement
    row: int  # logical bus row; lower/upper row zero faces entanglement
    col: int
    role: str  # slm, load, shuttle
    physical_row: int
    physical_col: int
    member: int | None = None


@dataclass(frozen=True)
class PatchBus:
    """Parallel transfer edges; +1 follows src[i] -> dst[i], -1 reverses."""
    id: str
    kind: str
    src: tuple[str, ...]
    dst: tuple[str, ...]

    def edges(self):
        return tuple(zip(self.src, self.dst))

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "src": list(self.src), "dst": list(self.dst)}


@dataclass(frozen=True)
class BusTopology:
    nodes: dict[str, BusNode]
    buses: tuple[PatchBus, ...]
    slm_shape: tuple[int, int]  # rows, columns
    entanglement_shape: tuple[int, int]  # rows, load/shuttle pairs per row
    partition: str = "bit"
    pair_axis: str = "horizontal"

    @classmethod
    def from_processor(cls, processor: Processor, *, partition="bit"):
        if partition not in {"bit", "row"}:
            raise ValueError("unsupported bus partition")
        cfg = processor.config
        if cfg.b1 < cfg.a2:
            raise ValueError("SLM columns b1 must be >= entanglement pair columns a2 for cross-zone buses")
        nodes = {}
        for patch in processor.patches.values():
            if patch.zone in {"storage", "measurement"}:
                zone = "lower" if patch.zone == "storage" else "upper"
                row = cfg.a1-1-patch.row if zone == "lower" else patch.row
                node = BusNode(patch.id, zone, row, patch.col, "slm", patch.row, patch.col)
            elif patch.zone == "entanglement" and patch.member in (0, 1):
                pair_row, pair_col = map(int, patch.pair.split(":")[1:])
                node = BusNode(patch.id, "entanglement", pair_row, pair_col,
                               "load" if patch.member == 0 else "shuttle",
                               patch.row, patch.col, patch.member)
            else:
                raise ValueError("unsupported processor patch for bus topology")
            nodes[patch.id] = node
        lookup = {(node.zone, node.row, node.col, node.role): key for key, node in nodes.items()}
        buses = []

        def hypercube(zone, role, rows, cols, prefix):
            for row in range(rows):
                for bit in range((cols-1).bit_length()):
                    mask = 1 << bit
                    pairs = [(lookup[zone, row, col, role], lookup[zone, row, col ^ mask, role])
                             for col in range(cols) if not col & mask and col ^ mask < cols]
                    if pairs:
                        buses.append(PatchBus(f"{prefix}:row:{row}:bit:{bit}", "row-hypercube",
                                              tuple(a for a, _ in pairs), tuple(b for _, b in pairs)))
            for col in range(cols):
                for bit in range((rows-1).bit_length()):
                    mask = 1 << bit
                    pairs = [(lookup[zone, row, col, role], lookup[zone, row ^ mask, col, role])
                             for row in range(rows) if not row & mask and row ^ mask < rows]
                    if pairs:
                        buses.append(PatchBus(f"{prefix}:column:{col}:bit:{bit}", "column-hypercube",
                                              tuple(a for a, _ in pairs), tuple(b for _, b in pairs)))

        hypercube("lower", "slm", cfg.a1, cfg.b1, "lower")
        hypercube("upper", "slm", cfg.a1, cfg.b1, "upper")
        hypercube("entanglement", "shuttle", cfg.b2, cfg.a2, "entanglement:shuttle")
        for row in range(cfg.b2):
            buses.append(PatchBus(f"entanglement:load-to-shuttle:row:{row}", "load-shuttle",
                tuple(lookup["entanglement", row, col, "load"] for col in range(cfg.a2)),
                tuple(lookup["entanglement", row, col, "shuttle"] for col in range(cfg.a2))))
        for zone, row in (("lower", 0), ("upper", cfg.b2-1)):
            buses.append(PatchBus(f"cross:{zone}", f"cross-{zone}",
                tuple(lookup["entanglement", row, col, "load"] for col in range(cfg.a2)),
                tuple(lookup[zone, 0, col, "slm"] for col in range(cfg.a2))))
        if partition == "bit":
            merged = {}
            for bus in buses:
                if bus.kind in {"row-hypercube", "column-hypercube"}:
                    axis = "row" if bus.kind == "row-hypercube" else "column"
                    prefix = bus.id.split(f":{axis}:")[0]
                    direction = "horizontal" if axis == "row" else "vertical"
                    key = f"{prefix}:{direction}:bit:{bus.id.rsplit(':', 1)[1]}"
                elif bus.kind == "load-shuttle":
                    key = "entanglement:load-to-shuttle"
                else:
                    key = bus.id
                previous = merged.get(key)
                merged[key] = PatchBus(key, bus.kind,
                    (previous.src if previous else ()) + bus.src,
                    (previous.dst if previous else ()) + bus.dst)
            buses = list(merged.values())
        result = cls(nodes, tuple(buses), (cfg.a1, cfg.b1), (cfg.b2, cfg.a2), partition,
                     "vertical" if processor.has_roads else "horizontal")
        result.validate()
        return result

    def adjacency(self):
        """Undirected neighbors keyed by the preserved physical patch ID."""
        neighbors = {key: set() for key in self.nodes}
        for bus in self.buses:
            for source, target in bus.edges():
                neighbors[source].add(target)
                neighbors[target].add(source)
        return {key: tuple(sorted(values)) for key, values in neighbors.items()}

    def edge_bus_directions(self, source, target):
        """Return (bus ID, +/-1) choices for one directed transfer."""
        if source not in self.nodes or target not in self.nodes:
            raise KeyError("unknown patch in bus edge lookup")
        choices = []
        for bus in self.buses:
            for a, b in bus.edges():
                if (source, target) == (a, b):
                    choices.append((bus.id, 1))
                elif (source, target) == (b, a):
                    choices.append((bus.id, -1))
        return tuple(choices)

    def validate(self):
        """Check all and only the configured bit-flip, local and boundary edges."""
        rows, cols = self.slm_shape
        ent_rows, ent_cols = self.entanglement_shape
        if any(type(n) is not int or n < 1 for n in (*self.slm_shape, *self.entanglement_shape)):
            raise ValueError("bus lattice dimensions must be positive integers")
        if cols < ent_cols:
            raise ValueError("SLM columns must cover every cross-zone load column")
        coordinates = {}
        for key, node in self.nodes.items():
            if key != node.patch_id:
                raise ValueError("bus node key disagrees with physical patch ID")
            if node.zone in {"lower", "upper"}:
                if (node.role != "slm" or node.member is not None
                        or not 0 <= node.row < rows or not 0 <= node.col < cols
                        or node.physical_row != (rows-1-node.row if node.zone == "lower" else node.row)
                        or node.physical_col != node.col):
                    raise ValueError("invalid SLM bus node numbering")
            elif node.zone == "entanglement":
                member = 0 if node.role == "load" else 1 if node.role == "shuttle" else None
                if (member is None or node.member != member
                        or not 0 <= node.row < ent_rows or not 0 <= node.col < ent_cols
                        or node.physical_row != (2*node.row+member if self.pair_axis == "vertical" else node.row)
                        or node.physical_col != (node.col if self.pair_axis == "vertical" else 2*node.col+member)):
                    raise ValueError("invalid entanglement load/shuttle numbering")
            else:
                raise ValueError("unknown bus node zone")
            coordinate = (node.zone, node.row, node.col, node.role)
            if coordinate in coordinates:
                raise ValueError("duplicate logical bus node")
            coordinates[coordinate] = key
        expected_node_count = 2*rows*cols+2*ent_rows*ent_cols
        if len(self.nodes) != expected_node_count:
            raise ValueError("bus topology must cover every SLM and entanglement patch")

        expected = set()
        for (zone, row, col, role), key in coordinates.items():
            if role in {"slm", "shuttle"}:
                height, width = (rows, cols) if role == "slm" else (ent_rows, ent_cols)
                for axis, size in ((0, height), (1, width)):
                    coordinate = row if axis == 0 else col
                    for bit in range((size-1).bit_length()):
                        changed = coordinate ^ (1 << bit)
                        if changed < size:
                            other = (zone, changed, col, role) if axis == 0 else (zone, row, changed, role)
                            expected.add(frozenset((key, coordinates[other])))
            if role == "load":
                expected.add(frozenset((key, coordinates[zone, row, col, "shuttle"])))
                for destination, boundary in (("lower", 0), ("upper", ent_rows-1)):
                    if row == boundary:
                        expected.add(frozenset((key, coordinates[destination, 0, col, "slm"])))
        seen, bus_ids = set(), set()
        for bus in self.buses:
            if not bus.id or bus.id in bus_ids or not bus.src or len(bus.src) != len(bus.dst):
                raise ValueError("bus IDs must be unique and parallel endpoints nonempty and equally sized")
            bus_ids.add(bus.id)
            if len(set(bus.src+bus.dst)) != 2*len(bus.src):
                raise ValueError("parallel bus edges must not reuse an endpoint")
            signatures = set()
            for source, target in bus.edges():
                if source not in self.nodes or target not in self.nodes:
                    raise ValueError("bus references an unknown physical patch")
                edge = frozenset((source, target))
                if edge not in expected or edge in seen:
                    raise ValueError("illegal or duplicate bus edge")
                a, b = self.nodes[source], self.nodes[target]
                if bus.kind in {"row-hypercube", "column-hypercube"}:
                    axis = "col" if bus.kind == "row-hypercube" else "row"
                    other = "row" if axis == "col" else "col"
                    delta = getattr(a, axis) ^ getattr(b, axis)
                    if (a.zone != b.zone or a.role != b.role or a.role not in {"slm", "shuttle"}
                            or getattr(a, other) != getattr(b, other) or delta == 0 or delta & (delta-1)
                            or getattr(a, axis) >= getattr(b, axis)):
                        raise ValueError("invalid directed hypercube bus")
                    signatures.add((a.zone, a.role, delta) if self.partition == "bit"
                                   else (a.zone, a.role, getattr(a, other), delta))
                elif bus.kind == "load-shuttle":
                    if (a.zone != "entanglement" or b.zone != "entanglement"
                            or (a.role, b.role) != ("load", "shuttle") or (a.row, a.col) != (b.row, b.col)):
                        raise ValueError("load bus must connect only its own paired shuttle")
                    signatures.add((a.zone,) if self.partition == "bit" else (a.zone, a.row))
                elif bus.kind in {"cross-lower", "cross-upper"}:
                    destination = bus.kind.removeprefix("cross-")
                    if (a.zone != "entanglement" or a.role != "load" or b.zone != destination
                            or a.row != (0 if destination == "lower" else ent_rows-1)
                            or b.row != 0 or a.col != b.col):
                        raise ValueError("invalid cross-zone boundary bus")
                    signatures.add((a.zone, a.row, b.zone, b.row))
                else:
                    raise ValueError("unknown patch bus kind")
                seen.add(edge)
            if len(signatures) != 1:
                raise ValueError("a parallel bus must share one region, fixed row/column and bit dimension")
        if self.partition == "bit":
            groups = [(b.kind, next(iter({
                (self.nodes[a].zone, self.nodes[a].role,
                 (self.nodes[a].col ^ self.nodes[z].col) if b.kind == "row-hypercube"
                 else (self.nodes[a].row ^ self.nodes[z].row))
                for a, z in b.edges()}))) if b.kind in {"row-hypercube", "column-hypercube"}
                else (b.kind,) for b in self.buses]
            if len(groups) != len(set(groups)):
                raise ValueError("one region/direction/bit must belong to exactly one BUS")
        if seen != expected:
            raise ValueError("bus topology is missing required transfer edges")
        adjacency = self.adjacency()
        reached, frontier = set(), [next(iter(self.nodes))]
        while frontier:
            node = frontier.pop()
            if node not in reached:
                reached.add(node)
                frontier.extend(adjacency[node])
        if reached != set(self.nodes):
            raise ValueError("bus topology must be connected")
        return {"valid": True, "nodes": len(self.nodes), "buses": len(self.buses), "edges": len(seen)}

    def to_dict(self):
        self.validate()
        return {
            "schema": "ftqc.patch-bus-topology.v3" if self.pair_axis == "vertical" else
                "ftqc.patch-bus-topology.v2" if self.partition == "bit" else "ftqc.patch-bus-topology.v1",
            **({"bus_resources": {"aod_units_per_execution": 1, "exclusive_aod": True,
                                   "uniform_direction_per_execution": True, "selectable_subset": True}}
               if self.partition == "bit" else {}),
            "slm_shape": list(self.slm_shape),
            "entanglement_shape": list(self.entanglement_shape),
            "numbering": {
                "physical_patch_ids": "preserved from Processor",
                "lower_rows": "row 0 nearest entanglement; bus_row = a1 - 1 - physical_row",
                "upper_rows": "row 0 nearest entanglement; bus_row = physical_row",
                "entanglement_rows": "bottom to top; bus_row = (physical_row - member) / 2" if self.pair_axis == "vertical"
                    else "bottom to top; bus_row = physical_row",
                "columns": "left to right; entanglement members share a bus column",
                "entanglement_roles": "member 0 = lower load; member 1 = upper shuttle" if self.pair_axis == "vertical"
                    else "member 0 = load; member 1 = its own right shuttle",
                "direction": "+1 follows src[i] to dst[i]; -1 reverses the edge",
                "non_power_of_two": "bit-flip edges are included only when the target exists",
            },
            "operation_regions": {"measurement": ["upper"], "reset": ["lower", "upper", "entanglement"]},
            "nodes": {key: asdict(node) for key, node in self.nodes.items()},
            "buses": [bus.to_dict() for bus in self.buses],
        }
