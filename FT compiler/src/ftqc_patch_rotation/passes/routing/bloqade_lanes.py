"""Call Bloqade Lanes directly for virtual-patch mapping and bus routing.

Each native atom stands for one data/check block and each native location
stands for one patch. Shared data/check storage is handled by the caller's
block occupancy rules, outside the native one-atom-per-location model.
"""
from dataclasses import asdict, dataclass
import importlib
from importlib import metadata
import json
from types import SimpleNamespace

from ftqc_patch_rotation.errors import RoutingError
from ftqc_patch_rotation.ir.routing import Mapping, Move


SUPPORTED_VERSION = "0.11.9"


def _load_bloqade():
    try:
        native = importlib.import_module("bloqade.lanes.bytecode")
        encoding = importlib.import_module("bloqade.lanes.bytecode.encoding")
        layout = importlib.import_module("bloqade.lanes.heuristics.logical.layout")
        version = metadata.version("bloqade-lanes")
    except (ImportError, metadata.PackageNotFoundError) as exc:
        raise RoutingError(
            "Bloqade bus routing requires the optional dependency "
            f"bloqade-lanes=={SUPPORTED_VERSION}; install it in the active Python environment"
        ) from exc
    if version != SUPPORTED_VERSION:
        raise RoutingError(f"Bloqade bus routing supports bloqade-lanes=={SUPPORTED_VERSION}, got {version}")
    return native, encoding, layout, version


@dataclass(frozen=True)
class LaneHopGroup:
    bus_id: str
    direction: str
    moves: tuple[Move, ...]
    native_lane_addresses: tuple[int, ...]

    def to_dict(self):
        return asdict(self)


class BloqadeLaneRouter:
    """A direct native solver adapter, with no local routing-search fallback.

    ``initial_mapping`` calls the official logical-layout heuristic with
    lower-zone home candidates only. ``place_pair`` calls native loose-goal
    CZ placement; ``route_block`` executes native fixed-target routing.
    """

    def __init__(self, processor, topology, *, seed=0, max_expansions=100_000):
        topology.validate()
        self.processor, self.topology = processor, topology
        self.native, self.encoding, self.layout, self.package_version = _load_bloqade()
        self.seed, self.max_expansions = seed, max_expansions
        self.trace = []
        self._zone_ids = {"lower": 0, "entanglement": 1, "upper": 2}
        self._native_bus_ids = {}
        self.arch_spec_dict = self._build_architecture()
        encoded = json.dumps(self.arch_spec_dict)
        self.native_arch = self.native.ArchSpec.from_json_validated(encoded)
        self.engine = self.native.SearchEngine.from_json_validated(encoded)
        self.search = self.native.MoveSearch.entropy(
            entropy_options=self.native.EntropyOptions(seed=seed))
        self.solver = self.native.TargetSolver(self.engine, self.search)
        self.placement = self.native.LooseGoalCzPlacement(self.engine, self.search)

    def _build_architecture(self):
        """Pad repeated native word grids, blocking every nonexistent patch.

        Native words exist in every zone. Repeated padding coordinates keep
        each zone's bounding box within its real physical extent; padded
        locations have no patch or transport edge and are always blocked.
        """
        nodes = self.topology.nodes
        rows = 1+max(node.physical_row for node in nodes.values())
        cols = 1+max(node.physical_col for node in nodes.values())
        words = [{"sites": [[col, row]]} for row in range(rows) for col in range(cols)]
        self.addresses, self._patch_by_address = {}, {}
        for patch, node in nodes.items():
            address = self.native.LocationAddress(
                self._zone_ids[node.zone], node.physical_row*cols+node.physical_col, 0)
            self.addresses[patch] = address
            self._patch_by_address[address.encode()] = patch
        self._phantom_addresses = tuple(
            self.native.LocationAddress(zone, word, 0)
            for zone in self._zone_ids.values() for word in range(rows*cols)
            if self.native.LocationAddress(zone, word, 0).encode() not in self._patch_by_address)
        zones = []
        for name, zone_id in self._zone_ids.items():
            zone_nodes = [node for node in nodes.values() if node.zone == name]
            xs = {node.physical_col: float(self.processor.patch_anchor(node.patch_id)[0]) for node in zone_nodes}
            ys = {node.physical_row: float(self.processor.patch_anchor(node.patch_id)[1]) for node in zone_nodes}
            x_values = [xs.get(col, xs[max(xs)]) for col in range(cols)]
            y_values = [ys.get(row, ys[max(ys)]) for row in range(rows)]
            zones.append(dict(name=name, grid=dict(
                x_start=x_values[0], y_start=y_values[0],
                x_spacing=[b-a for a, b in zip(x_values, x_values[1:])],
                y_spacing=[b-a for a, b in zip(y_values, y_values[1:])]),
                site_buses=[], word_buses=[], words_with_site_buses=[],
                sites_with_word_buses=[0], entangling_pairs=[]))
        zones[self._zone_ids["entanglement"]]["entangling_pairs"] = [
            [self.addresses[a].word_id, self.addresses[b].word_id]
            for a, b in self.processor.pairs.values()]
        zone_buses = []
        for bus in self.topology.buses:
            sources = [self.addresses[patch] for patch in bus.src]
            targets = [self.addresses[patch] for patch in bus.dst]
            src_zones, dst_zones = {a.zone_id for a in sources}, {a.zone_id for a in targets}
            if len(src_zones) != 1 or len(dst_zones) != 1:
                raise RoutingError("a patch bus must have homogeneous source and destination zones")
            if src_zones == dst_zones:
                zone = sources[0].zone_id
                index = len(zones[zone]["word_buses"])
                zones[zone]["word_buses"].append(dict(
                    src=[a.word_id for a in sources], dst=[a.word_id for a in targets]))
                self._native_bus_ids[(int(self.native.MoveType.WORD), zone, index)] = bus.id
            else:
                index = len(zone_buses)
                zone_buses.append(dict(
                    src=[dict(zone_id=a.zone_id, word_id=a.word_id) for a in sources],
                    dst=[dict(zone_id=a.zone_id, word_id=a.word_id) for a in targets]))
                self._native_bus_ids[(int(self.native.MoveType.ZONE), sources[0].zone_id, index)] = bus.id
        paths = []
        if self.processor.has_roads:
            from ftqc_patch_rotation.roads import SiteRoads
            roads = SiteRoads(self.processor)
            native_bus = {bus: key for key, bus in self._native_bus_ids.items()}
            for bus in self.topology.buses:
                mt, zone_id, bus_id = native_bus[bus.id]
                move_type = next(value for value in (self.native.MoveType.WORD, self.native.MoveType.ZONE)
                                 if int(value) == mt)
                bit = int(bus.id.rsplit(":", 1)[1]) if ":bit:" in bus.id else 0
                for source, target in bus.edges():
                    for reverse in (False, True):
                        a, b = (target, source) if reverse else (source, target)
                        lane = self.native.LaneAddress(move_type, zone_id, self.addresses[source].word_id,
                            0, bus_id, self.native.Direction.BACKWARD if reverse else self.native.Direction.FORWARD)
                        points = roads.path(self.processor.patch_anchor(a), self.processor.patch_anchor(b), a, bit=bit)
                        paths.append(dict(lane=f"0x{lane.encode():016x}",
                                          waypoints=[[float(x), float(y)] for x, y in points]))
        return dict(version="2.0", words=words, zones=zones, zone_buses=zone_buses, paths=paths,
                    modes=[dict(name="all-patches", zones=list(self._zone_ids.values()), bitstring_order=[])],
                    feed_forward=True, atom_reloading=False)

    def _patch(self, address):
        try:
            return self._patch_by_address[address.encode()]
        except KeyError as exc:
            raise RoutingError("native solver selected a padded location without a physical patch") from exc

    def _blocked(self, blocked_patches):
        unknown = set(blocked_patches)-set(self.addresses)
        if unknown:
            raise RoutingError(f"unknown blocked patches: {sorted(unknown)}")
        return [*self._phantom_addresses, *(self.addresses[p] for p in sorted(set(blocked_patches)))]

    def _record(self, method, initial, blocked_patches, result, **extra):
        self.trace.append(dict(
            method=method, package="bloqade-lanes", package_version=self.package_version,
            initial=dict(initial), blocked_patches=sorted(set(blocked_patches)),
            status=result.status, cost=result.cost, nodes_expanded=result.nodes_expanded,
            native_lane_addresses=[[lane.encode() for lane in group] for group in result.move_layers],
            **extra))
        if result.status != "solved":
            raise RoutingError(f"Bloqade {method} returned {result.status} after {result.nodes_expanded} expansions")

    def initial_mapping(self, circuit):
        homes = sorted((patch for patch, node in self.topology.nodes.items() if node.zone == "lower"),
                       key=lambda patch: (self.addresses[patch].word_id, patch))
        if circuit.num_qubits > len(homes):
            raise RoutingError("lower storage capacity is insufficient for logical codes and shared check homes")
        # The official heuristic only reads these two architecture properties.
        # Restricting candidates keeps initialization in the user-selected zone
        # without copying or modifying Bloqade's mapping algorithm.
        candidates = tuple(self.encoding.LocationAddress(
            self.addresses[p].word_id, 0, self.addresses[p].zone_id) for p in homes)
        home_arch = SimpleNamespace(home_sites=candidates, max_qubits=len(candidates))
        heuristic = self.layout.LogicalLayoutHeuristic(arch_spec=home_arch)
        qubits = tuple(range(circuit.num_qubits))
        stages = [(op.qubits,) for op in circuit.operations() if op.kind == "cz"]
        result = heuristic.compute_layout(qubits, stages)
        mapping = {q: self._patch(self.native.LocationAddress(addr.zone_id, addr.word_id, addr.site_id))
                   for q, addr in zip(qubits, result)}
        self.trace.append(dict(method="LogicalLayoutHeuristic.compute_layout", package="bloqade-lanes",
                               package_version=self.package_version, candidates=homes,
                               stages=stages, mapping=mapping,
                               shared_home_policy="data/check use disjoint physical sites in the mapped patch"))
        return Mapping(mapping, mapping.copy())

    def place_pair(self, positions, pairtuple, blocked_patches=()):
        """Choose a two-data-block CZ placement using the native solver.

        Other co-located blocks are not entered as duplicate native atoms;
        the caller supplies their stationary patch reservations as obstacles.
        Returned native paths are evidence only: the caller routes each block
        with its complete occupancy rules before executing the chosen gate.
        """
        a, b = pairtuple
        initial = {block: positions[block] for block in (a, b)}
        if a == b or len(set(initial.values())) != 2:
            raise RoutingError("native CZ placement requires two distinct blocks at distinct patches")
        blocked_patches = tuple(blocked_patches)
        result = self.placement.solve_pairs(
            {block: self.addresses[patch] for block, patch in initial.items()},
            [(a, b)], self._blocked(blocked_patches), self.max_expansions)
        self._record("LooseGoalCzPlacement.solve_pairs", initial, blocked_patches, result, pair=list(pairtuple))
        goals = {block: self._patch(address) for block, address in result.goal_config.items()}
        self.trace[-1]["goal_config"] = goals
        pair_id = self.processor.pair_of(goals[a])
        if pair_id is None or self.processor.pair_of(goals[b]) != pair_id or goals[a] == goals[b]:
            raise RoutingError("native CZ placement did not choose distinct members of one physical pair")
        return goals

    def route_block(self, block, start, target, blocked_patches):
        """Route one block through explicit native bus moves and replay them."""
        if start not in self.addresses or target not in self.addresses:
            raise RoutingError("unknown start or target patch")
        blocked_patches = tuple(blocked_patches)
        if start in blocked_patches or target in blocked_patches:
            raise RoutingError("moving block start and target must be excluded from stationary obstacles")
        if start == target:
            return []
        blocked = self._blocked(blocked_patches)
        initial = {block: self.addresses[start]}
        result = self.solver.solve(initial, {block: self.addresses[target]}, blocked, self.max_expansions)
        self._record("TargetSolver.solve", {block: start}, blocked_patches, result, target={block: target})
        # Add stationary obstacles to independent native replay as spectators.
        state_locations = dict(initial)
        next_spectator = max(block+1, 1_000_000)
        for address in blocked:
            state_locations[next_spectator] = address
            next_spectator += 1
        state = self.native.AtomStateData.from_qubit_locations(state_locations)
        groups = []
        for lanes in result.move_layers:
            validated = state.validate_moves(lanes, self.native_arch)
            moves = tuple(Move(q, self._patch(src), self._patch(dst)) for q, src, dst, lane in validated.movers)
            if any(move.qubit != block for move in moves):
                raise RoutingError("native route attempted to move a stationary obstacle")
            keys = {(self._native_bus_ids[(int(lane.move_type), lane.zone_id, lane.bus_id)],
                     "forward" if lane.direction == self.native.Direction.FORWARD else "backward")
                    for lane in lanes}
            if len(keys) != 1:
                raise RoutingError("native move layer mixes patch buses or directions")
            bus_id, direction = keys.pop()
            for move in moves:
                numeric_direction = 1 if direction == "forward" else -1
                if (bus_id, numeric_direction) not in self.topology.edge_bus_directions(move.start, move.target):
                    raise RoutingError("native lane does not match the configured patch bus")
            if moves:
                groups.append(LaneHopGroup(bus_id, direction, moves, tuple(lane.encode() for lane in lanes)))
            state = state.apply_validated(validated)
        if state.qubit_to_locations.get(block) != self.addresses[target]:
            raise RoutingError("native route replay did not reach its target")
        self.trace[-1]["layers"] = [group.to_dict() for group in groups]
        return groups
