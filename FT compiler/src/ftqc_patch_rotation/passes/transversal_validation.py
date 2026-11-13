"""Replay transversal IR without invoking the route or placement planner."""
import networkx as nx

from ftqc_patch_rotation.codes import rotated_surface_layout
from ftqc_patch_rotation.codes.patch_layout import rotated_patch_layout
from ftqc_patch_rotation.errors import RoutingError
from ftqc_patch_rotation.passes.routing.aod import apply_stage
from ftqc_patch_rotation.passes.routing.semantics import _check_input, _check_mapping
from ftqc_patch_rotation.passes.transversal_protocols import initial_states, logical_actions, se_actions, update_state


def _validate_se_alignment(step, patch_layout, offset_mode):
    """Replay selected check positions independently of the SE action builder."""
    data, anc = 2*step.logical_qubit, 2*step.logical_qubit+1
    check_coords = {i: (x, y) for i, x, y in patch_layout.checks}
    data_coords = {i: (x, y) for i, x, y in patch_layout.data}
    offsets = {i: (0, 0) for i in check_coords}
    for action in step.actions:
        if action.kind == "block_offset":
            if action.blocks != (anc,) or action.offset is None or len(action.offset) != 2:
                raise RoutingError("invalid SE offset block or displacement")
            dx, dy = action.offset
            if type(dx) is not int or type(dy) is not int:
                raise RoutingError("SE offsets must be integer site displacements")
            if offset_mode == "per-check":
                selected = action.targets
                if (not selected or len(set(selected)) != len(selected)
                        or any(b != anc or i not in check_coords for b, i in selected)):
                    raise RoutingError("invalid SE offset check selectors")
            else:
                if action.targets:
                    raise RoutingError("legacy SE offsets must move the whole check block")
                selected = tuple((anc, i) for i in check_coords)
            for _, i in selected:
                x, y = check_coords[i]
                if not (0 <= x+dx < patch_layout.side and 0 <= y+dy < patch_layout.side):
                    raise RoutingError("SE offset leaves the reserved patch")
                offsets[i] = action.offset
        elif action.gate == "cx":
            used = set()
            for a, b in action.pairs:
                if {a[0], b[0]} != {data, anc} or a in used or b in used:
                    raise RoutingError("SE CX pairs must be a data/check matching")
                used.update((a, b))
                ds, cs = (a[1], b[1]) if a[0] == data else (b[1], a[1])
                if ds not in data_coords or cs not in check_coords:
                    raise RoutingError("unknown SE interaction site")
                expected = tuple(data_coords[ds][i]-check_coords[cs][i] for i in (0, 1))
                if offsets[cs] != expected:
                    raise RoutingError("SE CX check is not aligned with its data partner")
        elif any(o != (0, 0) for o in offsets.values()):
            raise RoutingError("SE fold and auxiliary preparation/readout require zero check offsets")
    if any(o != (0, 0) for o in offsets.values()):
        raise RoutingError("SE leaves displaced checks")


def validate_transversal(circuit, processor, program):
    if program.transport_mode == "bloqade-lanes":
        from ftqc_patch_rotation.passes.bus_validation import validate_bus_transversal
        return validate_bus_transversal(circuit, processor, program)
    _check_input(circuit)
    _check_mapping(program.mapping, circuit, processor)
    if processor.config.code_kind != "rotated_surface" or processor.site_grid_size < 2*processor.config.d+3:
        raise RoutingError("transversal patch geometry mismatch")
    if program.se_offset_mode not in {"whole-block", "per-check"}:
        raise RoutingError("unsupported SE offset mode")
    homes = {**{2*q: p for q, p in program.mapping.initial_data_patch.items()},
             **{2*q+1: p for q, p in program.mapping.ancilla_patch.items()}}
    positions = homes.copy()
    states = initial_states(rotated_surface_layout(processor.config.d), circuit.num_qubits)
    resource_ops = [op for op in circuit.operations() if op.kind in {"prepare_t", "measure_t0", "measure_t1"}]
    if resource_ops:
        meta = program.frontend_metadata
        if (meta.get("model") != "reusable-encoded-T-static-branch-v1"
                or type(meta.get("algorithm_qubits")) is not int
                or meta["algorithm_qubits"] != circuit.num_qubits-1
                or meta.get("resource_qubits") != [circuit.num_qubits-1]):
            raise RoutingError("T resource operations require explicit reusable-resource assumptions")
        resource = circuit.num_qubits-1
        expected = ["prepare_t"]
        for index, injection in enumerate(meta.get("injections", [])):
            bit = injection.get("assumed_measurement")
            if (injection.get("index") != index or type(bit) is not int or bit not in (0, 1)
                    or injection.get("resource_qubit") != resource
                    or type(injection.get("data_qubit")) is not int
                    or not 0 <= injection["data_qubit"] < resource
                    or injection.get("gate") not in {"t", "tdg"}):
                raise RoutingError("invalid T injection provenance")
            expected.extend((f"measure_t{bit}", "prepare_t"))
        if ([op.kind for op in resource_ops] != expected or any(op.qubits != (resource,) for op in resource_ops)):
            raise RoutingError("T resource consume/replenish lifecycle mismatch")
    rounds, offset, done, pending = [0]*circuit.num_qubits, 0, set(), []
    anchors = program.se_after_nodes
    if len(set(anchors)) != len(anchors) or any(type(n) is not int or n not in circuit.dag
            or circuit.operation(n).kind in {"s", "sdg", "rot", "barrier"} for n in anchors):
        raise RoutingError("invalid SE anchors")
    ancestors = {n: nx.ancestors(circuit.dag, n) for n in circuit.dag}
    storage = processor.data_patches+processor.ancilla_patches
    sharing = {b: b//2 for b in homes}
    owners = {p: q for q, p in program.mapping.initial_data_patch.items()}
    patch_layout = rotated_patch_layout(processor.config.d, processor.site_grid_size)
    for step in program.steps:
        if step.kind == "block_move":
            if any((step.node_id is not None, step.logical_gate is not None, step.actions,
                    step.round_index is not None, step.measurement_offset is not None,
                    step.readouts, step.logical_qubit is not None)):
                raise RoutingError("block move carries unexpected operation metadata")
            if any(type(m.qubit) is not int or m.qubit not in positions for m in step.moves):
                raise RoutingError("unknown moving block")
            apply_stage(positions, step.moves, processor, storage_patches=storage,
                        sharing_groups=sharing, storage_owners=owners)
            continue
        if step.kind not in ("logical", "se") or step.moves:
            raise RoutingError("invalid transversal step kind")
        op = None
        if step.node_id is not None:
            if type(step.node_id) is not int or step.node_id not in circuit.dag or step.node_id in done:
                raise RoutingError("duplicate or unknown logical node")
            if pending or not ancestors[step.node_id] <= done:
                raise RoutingError("unfinished logical or SE predecessor")
            op = circuit.operation(step.node_id)
            if step.logical_gate != op.kind:
                raise RoutingError("logical operation disagrees with DAG")
        if step.kind == "se":
            q = step.logical_qubit
            if type(q) is not int or not 0 <= q < circuit.num_qubits:
                raise RoutingError("invalid SE block")
            if op is not None:
                if op.kind not in ("s", "sdg") or op.qubits != (q,):
                    raise RoutingError("SE logical gate must be S/Sdg")
            elif not pending or pending.pop(0) != q or step.logical_gate != "id":
                raise RoutingError("unexpected conventional SE round")
            data, anc = 2*q, 2*q+1
            pair = processor.pair_of(positions[data])
            if pair is None or processor.pair_of(positions[anc]) != pair:
                raise RoutingError("SE requires data/check blocks in the same entanglement pair")
            if {b for b, p in positions.items() if processor.pair_of(p) == pair} != {data, anc}:
                raise RoutingError("incorrect SE pair occupancy")
            if step.round_index != rounds[q] or step.measurement_offset != offset:
                raise RoutingError("incorrect SE measurement context")
            actions, readouts = se_actions(states[q], q, step.logical_gate, rounds[q], offset,
                                          selective_offsets=program.se_offset_mode == "per-check")
            if step.actions != actions or step.readouts != readouts:
                raise RoutingError("SE offsets, selections or fold protocol disagree")
            _validate_se_alignment(step, patch_layout, program.se_offset_mode)
            offset += len(readouts)
            rounds[q] += 1
        else:
            if op is None or op.kind in ("s", "sdg"):
                raise RoutingError("missing logical operation or unexpanded S")
            if op.kind in {"measure_t0", "measure_t1"}:
                if (step.round_index is not None or step.measurement_offset != offset
                        or step.logical_qubit != op.qubits[0] or step.readouts != ((offset, -1, "Z"),)):
                    raise RoutingError("logical T readout context mismatch")
                offset += 1
            elif any((step.round_index is not None, step.measurement_offset is not None,
                      step.readouts, step.logical_qubit is not None)):
                raise RoutingError("ordinary operation carries SE metadata")
            if step.actions != logical_actions(op, states):
                raise RoutingError("incorrect transversal gate or deformation operands")
            if op.kind == "cz":
                blocks = {2*q for q in op.qubits}
                pair = processor.pair_of(positions[2*op.qubits[0]])
                occupants = {b for b, p in positions.items() if processor.pair_of(p) == pair}
                if pair is None or occupants != blocks:
                    raise RoutingError("CZ requires exactly its two data blocks in one pair")
            update_state(op, states)
        if op is not None:
            done.add(op.id)
            if op.id in anchors:
                pending.extend(op.qubits)
    expected_permutations = tuple(tuple(int(c.rsplit(":", 1)[1]) for c in s.carriers_by_site) for s in states)
    if (done != set(circuit.dag) or pending or positions != program.final_positions
            or tuple(s.representation.orientation for s in states) != program.final_orientation
            or expected_permutations != program.final_data_permutations
            or offset != program.next_measurement_offset or tuple(rounds) != program.next_round_indices):
        raise RoutingError("incomplete transversal replay or incorrect final state")
    if any(positions[2*q+1] != program.mapping.ancilla_patch[q] for q in range(circuit.num_qubits)):
        raise RoutingError("check blocks must return to storage after their sessions")
    return {"valid": True, "logical_operations": len(done), "se_rounds": sum(rounds),
            "measurement_records": offset,
            "block_move_stages": sum(s.kind == "block_move" for s in program.steps)}
