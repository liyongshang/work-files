"""Compile patch operations through official Bloqade placement and lane solvers.

The adapter routes one rigid data/check block at a time. This preserves the
project's shared SLM homes without pretending that a Lane location can hold
two native atoms. Search and CZ target selection remain upstream operations.
"""
import json

from ftqc_patch_rotation.bus_architecture import BusTopology
from ftqc_patch_rotation.codes import rotated_surface_layout
from ftqc_patch_rotation.errors import RoutingError
from ftqc_patch_rotation.roads import bus_atom_paths
from ftqc_patch_rotation.ir.transversal import TransversalProgram, TransversalStep
from ftqc_patch_rotation.passes.routing.bloqade_lanes import BloqadeLaneRouter
from ftqc_patch_rotation.passes.transversal_protocols import (
    initial_states, logical_actions, se_actions, update_state,
)


def lower_bus_transversal(circuit, processor, *, seed=0, se_after_nodes=(), frontend_metadata=None):
    if processor.config.code_kind != "rotated_surface":
        raise ValueError("bus transversal compilation requires rotated_surface")
    supported = {"h", "cz", "rot", "s", "sdg", "x", "y", "z", "id", "barrier",
                 "prepare_t", "measure_t0", "measure_t1"}
    if any(op.kind not in supported for op in circuit.operations()):
        raise ValueError("unsupported bus transversal logical operation")
    se_after_nodes = tuple(se_after_nodes)
    if len(set(se_after_nodes)) != len(se_after_nodes) or any(
            type(n) is not int or n not in circuit.dag
            or circuit.operation(n).kind in {"s", "sdg", "rot", "barrier"} for n in se_after_nodes):
        raise ValueError("invalid bus SE anchors")
    topology = BusTopology.from_processor(processor)
    router = BloqadeLaneRouter(processor, topology, seed=seed)
    mapping = router.initial_mapping(circuit)
    positions = {**{2*q: p for q, p in mapping.initial_data_patch.items()},
                 **{2*q+1: p for q, p in mapping.ancilla_patch.items()}}
    gateways = {patch for bus in topology.buses if bus.kind.startswith("cross-")
                for patch in (*bus.src, *bus.dst) if topology.nodes[patch].role == "slm"}
    states = initial_states(rotated_surface_layout(processor.config.d), circuit.num_qubits)
    steps, rounds, measurement_offset = [], [0]*circuit.num_qubits, 0

    def shareable(block, other, patch):
        return block//2 == other//2 and processor.zone_of(patch) in {"storage", "measurement"}

    def obstacles(block):
        return {patch for other, patch in positions.items()
                if other != block and not shareable(block, other, patch)}

    def probe(block, target):
        if positions[block] == target:
            return (), None
        blocked = obstacles(block)
        if target in blocked:
            raise RoutingError("target patch is occupied by an incompatible block")
        groups = router.route_block(block, positions[block], target, blocked)
        return groups, len(router.trace)-1

    def commit(block, groups, solve_index):
        if solve_index is not None:
            router.trace[solve_index]["committed"] = True
        for group in groups:
            for move in group.moves:
                if move.qubit != block or positions[block] != move.start:
                    raise RoutingError("native route changed an unexpected block")
                if move.target in obstacles(block):
                    raise RoutingError("native route violates patch occupancy")
                positions[block] = move.target
            transport = {"bus_id": group.bus_id, "direction": group.direction,
                           "native_lane_addresses": list(group.native_lane_addresses),
                           "solve_index": solve_index}
            if processor.has_roads:
                transport.update(path_model="site-roads-v1",
                    atom_paths=bus_atom_paths(processor, group.moves, states, group.bus_id))
            steps.append(TransversalStep("block_move", moves=group.moves, transport=transport))

    def slm_candidates(block, *, zone=None, exclude=()):
        excluded = set(exclude)
        candidates = [p for p, node in topology.nodes.items()
                      if node.role == "slm" and p not in excluded and p not in obstacles(block)
                      and (zone is None or processor.zone_of(p) == zone)]
        # Park away from gateway row zero so a stored block does not consume
        # the only cross-zone landing pad. This is a capacity policy, not a
        # replacement for the upstream path search.
        return sorted(candidates, key=lambda p: (
            processor.zone_of(p) != ("measurement" if block % 2 else "storage"),
            -topology.nodes[p].row, topology.nodes[p].col, p))

    def relocate(block, candidates):
        failures = []
        for target in candidates:
            if target == positions[block]:
                continue
            try:
                groups, solve_index = probe(block, target)
            except RoutingError as error:
                failures.append(str(error))
                continue
            commit(block, groups, solve_index)
            return
        detail = failures[-1] if failures else "no compatible destination"
        raise RoutingError(f"cannot relocate block {block}: {detail}")

    def release_gateways(active):
        for block in sorted(positions):
            if block not in active and positions[block] in gateways:
                relocate(block, slm_candidates(block, exclude=gateways))

    def evacuate_entanglement(active):
        for block in sorted(positions, key=lambda b: (topology.nodes[positions[b]].role != "load", b)):
            if block not in active and processor.zone_of(positions[block]) == "entanglement":
                if topology.nodes[positions[block]].role == "shuttle":
                    pair = processor.pair_of(positions[block])
                    load = processor.pair_members(pair)[0]
                    occupants = [other for other, patch in positions.items() if patch == load]
                    for other in occupants:
                        # A shuttle has no direct cross-zone bus. Release its
                        # occupied load first, even if that block participates
                        # in the next gate, then evacuate the shuttle.
                        relocate(other, slm_candidates(other, exclude=gateways))
                relocate(block, slm_candidates(block, exclude=gateways))

    def move_to(targets):
        """Resolve patch capacity while delegating every path to TargetSolver."""
        seen = set()
        for _ in range(4*len(positions)*max(1, len(topology.nodes))):
            pending = [b for b, target in sorted(targets.items(), key=lambda item: (
                topology.nodes[item[1]].role != "shuttle", item[0])) if positions[b] != target]
            if not pending:
                return
            signature = tuple(sorted(positions.items()))
            if signature in seen:
                raise RoutingError("bus capacity scheduling repeated a configuration")
            seen.add(signature)
            progressed = False
            for block in pending:
                try:
                    groups, solve_index = probe(block, targets[block])
                except RoutingError:
                    continue
                commit(block, groups, solve_index)
                progressed = True
                break
            if progressed:
                continue
            # A shuttle's load gateway or a target may be occupied. Release a
            # stationary block into a free SLM patch, using the same native
            # route solver; no arbitrary endpoint jumps or local BFS exist.
            target_patches = set(targets.values())
            blockers = sorted(positions, key=lambda b: (
                positions[b] not in target_patches,
                processor.zone_of(positions[b]) != "entanglement", b))
            occupied = set(positions.values())
            for block in blockers:
                try:
                    relocate(block, slm_candidates(block, exclude=target_patches | occupied))
                except RoutingError:
                    continue
                progressed = True
                break
            if not progressed:
                raise RoutingError("no native bus route or compatible capacity buffer is available")
        raise RoutingError("bus capacity scheduling exceeded its relocation bound")

    def meet(pair):
        release_gateways(set(pair))
        evacuate_entanglement(set(pair))
        release_gateways(set(pair))
        a, b = pair
        if positions[a] == positions[b]:
            # The native occupancy map is injective. Separate this shared SLM
            # home first, preferably directly into a free shuttle patch.
            candidates = sorted((p for p, node in topology.nodes.items()
                                 if node.zone == "entanglement" and p not in positions.values()),
                                key=lambda p: (topology.nodes[p].role != "shuttle", p))
            relocate(a, candidates + slm_candidates(a, exclude=set(positions.values())))
        blocked = {patch for block, patch in positions.items()
                   if block not in pair and patch not in {positions[a], positions[b]}}
        goals = router.place_pair(positions, pair, blocked)
        router.trace[-1]["purpose"] = "CZ pair target selection; routes replayed with shared-SLM reservations"
        move_to(goals)

    def send_to_measurement(block):
        if processor.zone_of(positions[block]) == "measurement":
            return
        release_gateways({block})
        candidates = slm_candidates(block, zone="measurement", exclude=set(positions.values()))
        try:
            relocate(block, candidates)
            return
        except RoutingError:
            pass
        # In a one-pair architecture a block in the shuttle cannot exit while
        # its load is occupied, even by its own data partner.
        for other in sorted(positions):
            if other != block and processor.zone_of(positions[other]) == "entanglement":
                relocate(other, slm_candidates(other, exclude=set(positions.values())))
        relocate(block, slm_candidates(block, zone="measurement", exclude=set(positions.values())))

    def session(q, gate, node_id):
        nonlocal measurement_offset
        data, anc = 2*q, 2*q+1
        meet((data, anc))
        actions, readouts = se_actions(states[q], q, gate, rounds[q], measurement_offset)
        if actions[-1].gate != "measure":
            raise RoutingError("SE recipe lacks its final auxiliary measurement")
        metadata = dict(node_id=node_id, logical_gate=gate, logical_qubit=q,
                        round_index=rounds[q], measurement_offset=measurement_offset)
        steps.append(TransversalStep("se_interaction", actions=actions[:-1], **metadata))
        send_to_measurement(anc)
        steps.append(TransversalStep("se_readout", actions=(actions[-1],), readouts=readouts, **metadata))
        measurement_offset += len(readouts)
        rounds[q] += 1

    for op in circuit.operations():
        if op.kind in {"s", "sdg"}:
            session(op.qubits[0], op.kind, op.id)
        else:
            if op.kind == "cz":
                meet(tuple(2*q for q in op.qubits))
            elif op.kind in {"measure_t0", "measure_t1"}:
                send_to_measurement(2*op.qubits[0])
            actions = logical_actions(op, states)
            if op.kind in {"measure_t0", "measure_t1"}:
                steps.append(TransversalStep("logical", node_id=op.id, logical_gate=op.kind, actions=actions,
                    logical_qubit=op.qubits[0], measurement_offset=measurement_offset,
                    readouts=((measurement_offset, -1, "Z"),)))
                measurement_offset += 1
            else:
                steps.append(TransversalStep("logical", node_id=op.id, logical_gate=op.kind, actions=actions))
            update_state(op, states)
        if op.id in se_after_nodes:
            for q in op.qubits:
                session(q, "id", None)

    metadata = {
        "package": "bloqade-lanes", "package_version": router.package_version,
        "initial_mapping_algorithm": "LogicalLayoutHeuristic.compute_layout",
        "placement_algorithm": "LooseGoalCzPlacement.solve_pairs",
        "routing_algorithm": "TargetSolver.solve", "search": "MoveSearch.entropy",
        "abstraction": "one virtual Lane atom per moving data/check block; shared SLM reservation adapter",
        "seed": seed, "trace": router.trace, "native_architecture": router.arch_spec_dict,
    }
    metadata = json.loads(json.dumps(metadata))
    result = TransversalProgram(mapping, tuple(steps), positions.copy(),
        tuple(state.representation.orientation for state in states),
        tuple(tuple(int(c.rsplit(":", 1)[1]) for c in state.carriers_by_site) for state in states),
        measurement_offset, tuple(rounds), se_after_nodes, frontend_metadata or {},
        "per-check", "bloqade-lanes", topology.to_dict(), metadata)
    from ftqc_patch_rotation.passes.bus_validation import validate_bus_transversal
    validate_bus_transversal(circuit, processor, result)
    return result
