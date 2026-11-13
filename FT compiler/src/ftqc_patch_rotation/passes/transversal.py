"""Reuse patch routing, add check-block transport and code-specific macros."""
from ftqc_patch_rotation.codes import rotated_surface_layout
from ftqc_patch_rotation.ir.transversal import TransversalProgram, TransversalStep
from ftqc_patch_rotation.passes.routing import route_and_schedule
from ftqc_patch_rotation.passes.routing.aod import apply_stage, plan_aod_stages
from ftqc_patch_rotation.passes.transversal_protocols import initial_states, logical_actions, se_actions, update_state


def block_homes(mapping):
    return {**{2*q: p for q, p in mapping.initial_data_patch.items()},
            **{2*q+1: p for q, p in mapping.ancilla_patch.items()}}


def lower_transversal(circuit, processor, *, seed=0, se_after_nodes=(), frontend_metadata=None):
    """Input already encoded Clifford blocks; output transversal IR.

    The existing scheduler supplies logical order and data-block routing.
    SE sessions temporarily bring all other blocks home, then restore the
    previous mapping. This conservative baseline preserves the existing
    routing decisions and avoids silently occupying an active CZ pair.
    """
    if processor.config.code_kind != "rotated_surface" or processor.site_grid_size < 2*processor.config.d+3:
        raise ValueError("transversal compiler requires rotated_surface patches of side >= 2d+3")
    supported = {"h", "cz", "rot", "s", "sdg", "x", "y", "z", "id", "barrier", "prepare_t", "measure_t0", "measure_t1"}
    if any(op.kind not in supported for op in circuit.operations()):
        raise ValueError("only the verified rotated Clifford subset is supported")
    se_after_nodes = tuple(se_after_nodes)
    if len(set(se_after_nodes)) != len(se_after_nodes) or any(
            type(n) is not int or n not in circuit.dag or circuit.operation(n).kind in {"s", "sdg", "rot", "barrier"}
            for n in se_after_nodes):
        raise ValueError("SE anchors must be distinct supported logical gate nodes")
    skeleton = route_and_schedule(circuit, processor, seed=seed)
    homes = block_homes(skeleton.mapping)
    positions = homes.copy()
    states = initial_states(rotated_surface_layout(processor.config.d), circuit.num_qubits)
    rounds, offset, steps = [0]*circuit.num_qubits, 0, []
    storage = processor.data_patches+processor.ancilla_patches
    sharing = {b: b//2 for b in homes}
    owners = {p: q for q, p in skeleton.mapping.initial_data_patch.items()}

    def move_to(target):
        for stage in plan_aod_stages(positions, target, processor, storage_patches=storage,
                                     sharing_groups=sharing, storage_owners=owners):
            steps.append(TransversalStep("block_move", moves=stage))
            apply_stage(positions, stage, processor, storage_patches=storage,
                        sharing_groups=sharing, storage_owners=owners)

    def session(q, gate, node_id):
        nonlocal offset
        previous = positions.copy()
        data, anc = 2*q, 2*q+1
        members = min((members for members in processor.pairs.values()),
            key=lambda pair: (processor.distance2(positions[data], pair[0])+
                              processor.distance2(positions[anc], pair[1]), pair))
        target = homes.copy()
        target[data], target[anc] = members
        move_to(target)
        actions, readouts = se_actions(states[q], q, gate, rounds[q], offset)
        steps.append(TransversalStep("se", node_id=node_id, logical_gate=gate,
            actions=actions, round_index=rounds[q], measurement_offset=offset,
            readouts=readouts, logical_qubit=q))
        offset += len(readouts)
        rounds[q] += 1
        move_to(previous)

    for block in skeleton.blocks:
        if block.kind == "aod":
            target = positions.copy()
            target.update({2*m.qubit: m.target for m in block.moves})
            move_to(target)
        else:
            for node_id in block.nodes:
                op = circuit.operation(node_id)
                if op.kind in ("s", "sdg"):
                    session(op.qubits[0], op.kind, node_id)
                else:
                    actions = logical_actions(op, states)
                    if op.kind in {"measure_t0", "measure_t1"}:
                        steps.append(TransversalStep("logical", node_id=node_id, logical_gate=op.kind, actions=actions,
                            logical_qubit=op.qubits[0], measurement_offset=offset, readouts=((offset, -1, "Z"),)))
                        offset += 1
                    else:
                        steps.append(TransversalStep("logical", node_id=node_id, logical_gate=op.kind, actions=actions))
                    update_state(op, states)
                if node_id in se_after_nodes:
                    for q in op.qubits:
                        session(q, "id", None)
    result = TransversalProgram(skeleton.mapping, tuple(steps), positions.copy(),
        tuple(s.representation.orientation for s in states),
        tuple(tuple(int(c.rsplit(":", 1)[1]) for c in s.carriers_by_site) for s in states),
        offset, tuple(rounds), se_after_nodes, frontend_metadata or {})
    from ftqc_patch_rotation.passes.transversal_validation import validate_transversal
    validate_transversal(circuit, processor, result)
    return result
