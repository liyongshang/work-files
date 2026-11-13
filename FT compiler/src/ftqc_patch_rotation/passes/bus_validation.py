"""Independently replay bus-constrained block moves and separated SE readout."""
from collections import Counter
import networkx as nx

from ftqc_patch_rotation.bus_architecture import BusTopology
from ftqc_patch_rotation.codes import rotated_patch_layout, rotated_surface_layout
from ftqc_patch_rotation.errors import RoutingError
from ftqc_patch_rotation.passes.routing.semantics import _check_input, _check_mapping
from ftqc_patch_rotation.passes.transversal_protocols import (
    initial_states, logical_actions, se_actions, update_state,
)


def _check_occupancy(positions, topology):
    occupants = {}
    for block, patch in positions.items():
        if patch not in topology.nodes:
            raise RoutingError("bus position references an unknown patch")
        occupants.setdefault(patch, []).append(block)
    for patch, blocks in occupants.items():
        if len(blocks) <= 1:
            continue
        if (topology.nodes[patch].zone == "entanglement" or len(blocks) != 2
                or blocks[0]//2 != blocks[1]//2):
            raise RoutingError("bus patch occupancy violates data/check sharing or entanglement exclusivity")


def _check_backend_provenance(program, nonempty):
    metadata = program.backend_metadata
    if not isinstance(metadata, dict):
        raise RoutingError("missing Bloqade backend provenance")
    version = metadata.get("package_version")
    initial = metadata.get("initial_mapping_algorithm")
    routing = metadata.get("routing_algorithm")
    trace = metadata.get("trace")
    if (not isinstance(version, str) or not version
            or not isinstance(initial, str) or "LogicalLayoutHeuristic" not in initial
            or not isinstance(routing, str) or "TargetSolver" not in routing
            or not isinstance(trace, list) or (nonempty and not trace)):
        raise RoutingError("missing Bloqade mapping/routing provenance")
    if nonempty and not any(isinstance(record, dict)
            and record.get("method") == "LogicalLayoutHeuristic.compute_layout"
            and record.get("package_version") == version for record in trace):
        raise RoutingError("missing native initial-mapping trace")
    layers = Counter()
    for solve_index, record in enumerate(trace):
        if (not isinstance(record, dict) or record.get("method") != "TargetSolver.solve"
                or record.get("status") != "solved" or record.get("committed") is not True):
            continue
        for layer in record.get("layers", []):
            try:
                key = (solve_index, layer["bus_id"], layer["direction"],
                       tuple((move["qubit"], move["start"], move["target"]) for move in layer["moves"]),
                       tuple(layer["native_lane_addresses"]))
                layers[key] += 1
            except (KeyError, TypeError):
                raise RoutingError("malformed native routing trace") from None
    return layers


def _check_resource_metadata(circuit, metadata):
    resource_ops = [op for op in circuit.operations()
                    if op.kind in {"prepare_t", "measure_t0", "measure_t1"}]
    if not resource_ops:
        return
    resource = circuit.num_qubits-1
    if (metadata.get("model") != "reusable-encoded-T-static-branch-v1"
            or type(metadata.get("algorithm_qubits")) is not int
            or metadata["algorithm_qubits"] != resource
            or metadata.get("resource_qubits") != [resource]):
        raise RoutingError("T resource operations require explicit reusable-resource assumptions")
    expected = ["prepare_t"]
    for index, injection in enumerate(metadata.get("injections", [])):
        bit = injection.get("assumed_measurement")
        if (injection.get("index") != index or type(bit) is not int or bit not in (0, 1)
                or injection.get("resource_qubit") != resource
                or type(injection.get("data_qubit")) is not int
                or not 0 <= injection["data_qubit"] < resource
                or injection.get("gate") not in {"t", "tdg"}):
            raise RoutingError("invalid T injection provenance")
        expected.extend((f"measure_t{bit}", "prepare_t"))
    if ([op.kind for op in resource_ops] != expected
            or any(op.qubits != (resource,) for op in resource_ops)):
        raise RoutingError("T resource consume/replenish lifecycle mismatch")


def _replay_move(step, positions, topology, buses, native_layers):
    if (step.node_id is not None or step.logical_gate is not None or step.actions
            or step.round_index is not None or step.measurement_offset is not None
            or step.readouts or step.logical_qubit is not None or not step.moves):
        raise RoutingError("bus move carries unexpected operation metadata")
    transport = step.transport
    if not isinstance(transport, dict) or transport.get("bus_id") not in buses:
        raise RoutingError("bus move has missing or unknown bus identity")
    direction = transport.get("direction")
    if direction not in {"forward", "backward"}:
        raise RoutingError("bus move has invalid direction")
    addresses = transport.get("native_lane_addresses")
    if (not isinstance(addresses, (tuple, list)) or len(addresses) != len(step.moves)
            or any(type(address) is not int or address < 0 for address in addresses)):
        raise RoutingError("bus move lacks native lane addresses")
    solve_index = transport.get("solve_index")
    if type(solve_index) is not int or solve_index < 0:
        raise RoutingError("bus move lacks its native solve index")
    key = (solve_index, transport["bus_id"], direction,
           tuple((move.qubit, move.start, move.target) for move in step.moves), tuple(addresses))
    if native_layers[key] < 1:
        raise RoutingError("bus move is absent from the native TargetSolver trace")
    native_layers[key] -= 1
    bus = buses[transport["bus_id"]]
    edges = set(bus.edges())
    if direction == "backward":
        edges = {(b, a) for a, b in edges}
    moving = set()
    for move in step.moves:
        if (type(move.qubit) is not int or move.qubit not in positions
                or move.qubit in moving or positions[move.qubit] != move.start
                or (move.start, move.target) not in edges):
            raise RoutingError("bus move is not a legal configured edge from the current position")
        moving.add(move.qubit)
    if (len({move.start for move in step.moves}) != len(step.moves)
            or len({move.target for move in step.moves}) != len(step.moves)):
        raise RoutingError("one native bus layer cannot reuse a source or destination")
    positions.update((move.qubit, move.target) for move in step.moves)
    _check_occupancy(positions, topology)


def validate_bus_transversal(circuit, processor, program):
    """Check saved execution without calling any mapping, routing or search API."""
    # Import only the position checker, never the planning entry points.
    from ftqc_patch_rotation.passes.transversal_validation import _validate_se_alignment

    _check_input(circuit)
    _check_mapping(program.mapping, circuit, processor)
    if (processor.config.code_kind != "rotated_surface"
            or processor.site_grid_size < 2*processor.config.d+3
            or program.transport_mode != "bloqade-lanes" or program.se_offset_mode != "per-check"):
        raise RoutingError("bus transversal geometry or transport model mismatch")
    topology = BusTopology.from_processor(processor, partition=(
        "row" if program.transport_topology.get("schema") == "ftqc.patch-bus-topology.v1" else "bit"))
    if program.transport_topology != topology.to_dict():
        raise RoutingError("saved bus topology disagrees with processor geometry")
    native_layers = _check_backend_provenance(program, bool(circuit.dag))
    _check_resource_metadata(circuit, program.frontend_metadata)
    buses = {bus.id: bus for bus in topology.buses}
    positions = {**{2*q: patch for q, patch in program.mapping.initial_data_patch.items()},
                 **{2*q+1: patch for q, patch in program.mapping.ancilla_patch.items()}}
    _check_occupancy(positions, topology)
    states = initial_states(rotated_surface_layout(processor.config.d), circuit.num_qubits)
    patch_layout = rotated_patch_layout(processor.config.d, processor.site_grid_size)
    anchors = program.se_after_nodes
    if (len(set(anchors)) != len(anchors) or any(type(node) is not int or node not in circuit.dag
            or circuit.operation(node).kind not in {"h", "cz", "x", "y", "z", "id"}
            for node in anchors)):
        raise RoutingError("invalid bus SE anchors")
    ancestors = {node: nx.ancestors(circuit.dag, node) for node in circuit.dag}
    done, active, pending = set(), {}, []
    rounds = [0]*circuit.num_qubits
    offset = reserved_offset = move_stages = bus_hops = 0

    def check_node(step, *, readout=False):
        if step.node_id is None:
            return None
        if (type(step.node_id) is not int or step.node_id not in circuit.dag
                or step.node_id in done):
            raise RoutingError("duplicate or unknown bus logical node")
        op = circuit.operation(step.node_id)
        if step.logical_gate != op.kind or not ancestors[op.id] <= done:
            raise RoutingError("bus logical gate or dependencies disagree with DAG")
        if not readout and (pending or any(q in active for q in op.qubits)):
            raise RoutingError("unfinished logical or SE predecessor")
        return op

    for step in program.steps:
        if step.kind == "block_move":
            if processor.has_roads:
                from ftqc_patch_rotation.roads import bus_atom_paths
                if (step.transport.get("path_model") != "site-roads-v1"
                        or step.transport.get("atom_paths") != bus_atom_paths(
                            processor, step.moves, states, step.transport.get("bus_id", ""))):
                    raise RoutingError("BUS atom road trajectories disagree with geometry or carrier state")
            _replay_move(step, positions, topology, buses, native_layers)
            move_stages += 1
            bus_hops += len(step.moves)
            continue
        if step.moves or step.transport:
            raise RoutingError("non-move step carries bus transport metadata")
        if step.kind == "se_interaction":
            q = step.logical_qubit
            if type(q) is not int or not 0 <= q < circuit.num_qubits or q in active:
                raise RoutingError("invalid or already active bus SE block")
            op = check_node(step)
            if op is not None:
                if op.kind not in {"s", "sdg"} or op.qubits != (q,):
                    raise RoutingError("SE logical gate must be S/Sdg")
            elif not pending or pending.pop(0) != q or step.logical_gate != "id":
                raise RoutingError("unexpected conventional bus SE round")
            data, anc = 2*q, 2*q+1
            pair = processor.pair_of(positions[data])
            if (pair is None or processor.pair_of(positions[anc]) != pair
                    or {b for b, patch in positions.items() if processor.pair_of(patch) == pair} != {data, anc}):
                raise RoutingError("bus SE requires exactly its data/check blocks in one entanglement pair")
            if (step.round_index != rounds[q] or step.measurement_offset != reserved_offset
                    or step.readouts):
                raise RoutingError("incorrect bus SE interaction context")
            actions, readouts = se_actions(states[q], q, step.logical_gate, rounds[q], reserved_offset)
            if step.actions != actions[:-1]:
                raise RoutingError("bus SE interaction offsets, selections or fold protocol disagree")
            _validate_se_alignment(step, patch_layout, "per-check")
            active[q] = (step.node_id, step.logical_gate, rounds[q], reserved_offset, actions[-1:], readouts)
            reserved_offset += len(readouts)
            continue
        if step.kind == "se_readout":
            q = step.logical_qubit
            if type(q) is not int or q not in active:
                raise RoutingError("SE readout has no active interaction session")
            expected = active[q]
            if ((step.node_id, step.logical_gate, step.round_index, step.measurement_offset,
                 step.actions, step.readouts) != expected or step.measurement_offset != offset):
                raise RoutingError("SE readout does not complete its interaction session")
            if topology.nodes[positions[2*q+1]].zone != "upper":
                raise RoutingError("SE measurement is only permitted in the upper measurement zone")
            op = check_node(step, readout=True)
            offset += len(step.readouts)
            rounds[q] += 1
            del active[q]
            if op is not None:
                done.add(op.id)
            continue
        if step.kind != "logical":
            raise RoutingError("invalid bus transversal step kind")
        op = check_node(step)
        if op is None or op.kind in {"s", "sdg"}:
            raise RoutingError("missing logical node or unexpanded bus S")
        if op.kind in {"measure_t0", "measure_t1"}:
            q = op.qubits[0]
            if (active or step.round_index is not None or step.measurement_offset != offset
                    or step.logical_qubit != q or step.readouts != ((offset, -1, "Z"),)):
                raise RoutingError("logical T measurement context mismatch")
            if topology.nodes[positions[2*q]].zone != "upper":
                raise RoutingError("logical measurement is only permitted in the upper measurement zone")
            offset += 1
            reserved_offset += 1
        elif (step.round_index is not None or step.measurement_offset is not None
                or step.readouts or step.logical_qubit is not None):
            raise RoutingError("ordinary bus operation carries SE metadata")
        if step.actions != logical_actions(op, states):
            raise RoutingError("incorrect bus transversal gate or deformation operands")
        if op.kind == "cz":
            qa, qb = op.qubits
            pair = processor.pair_of(positions[2*qa])
            if (pair is None or processor.pair_of(positions[2*qb]) != pair
                    or {b for b, patch in positions.items() if processor.pair_of(patch) == pair} != {2*qa, 2*qb}
                    or states[qa].representation.orientation == states[qb].representation.orientation):
                raise RoutingError("CZ requires exactly its opposite-orientation data blocks in one pair")
        update_state(op, states)
        done.add(op.id)
        if op.id in anchors:
            pending.extend(op.qubits)

    expected_permutations = tuple(tuple(int(carrier.rsplit(":", 1)[1])
                                       for carrier in state.carriers_by_site) for state in states)
    if (done != set(circuit.dag) or active or pending or offset != reserved_offset
            or positions != program.final_positions
            or tuple(state.representation.orientation for state in states) != program.final_orientation
            or expected_permutations != program.final_data_permutations
            or offset != program.next_measurement_offset or tuple(rounds) != program.next_round_indices):
        raise RoutingError("incomplete bus replay or incorrect final state")
    if any(topology.nodes[positions[2*q+1]].zone == "entanglement" for q in range(circuit.num_qubits)):
        raise RoutingError("completed check blocks must reside in an SLM storage/measurement zone")
    return {"valid": True, "logical_operations": len(done), "se_rounds": sum(rounds),
            "measurement_records": offset, "block_move_stages": move_stages,
            "bus_hops": bus_hops, "measurement_zone_only": True}
