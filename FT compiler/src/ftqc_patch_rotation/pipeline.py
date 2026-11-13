"""Compose the frontend, patch-rotation/lowering and routing passes."""
from ftqc_patch_rotation.ir.logical import CompiledCircuit
from ftqc_patch_rotation.passes.frontend import prepare_static_trace
from ftqc_patch_rotation.passes.patch_rotation import greedy_optimize
from ftqc_patch_rotation.passes.lowering import compile_circuit
from ftqc_patch_rotation.passes.routing import route_and_schedule
from ftqc_patch_rotation.serialization import load_compilation, save_compilation
from ftqc_patch_rotation.passes.se import compile_stabilizer_measurement


def compile_se_round(processor, data_patch=None, ancilla_patch=None, *,
                     initial_state=None, swap_directions=("D",)):
    """Compile the atom-level LRUD motion of one SE round in an occupied pair."""
    return compile_stabilizer_measurement(
        processor, data_patch, ancilla_patch, initial_state=initial_state,
        swap_directions=swap_directions)


def compile_processor(circuit, processor, optimizer=greedy_optimize, seed=0, cost_fn=len):
    """Return (logical DAG, hardware schedule, frontend metadata)."""
    if isinstance(circuit, CompiledCircuit):
        compiled = circuit
        metadata = {"seed": seed, "static_trace": True, "magic_state_conversion": None}
    else:
        static_circuit, metadata = prepare_static_trace(circuit, seed=seed)
        compiled = compile_circuit(static_circuit, optimizer)
    schedule = route_and_schedule(compiled, processor, seed=seed, cost_fn=cost_fn)
    return compiled, schedule, metadata


def compile_transversal(circuit, processor, optimizer=greedy_optimize, *, seed=0,
                        se_policy="required-only", t_measurements=None, routing_backend="bloqade-lanes"):
    """Return (rotated logical DAG, block-level transversal program).

    T/Tdg uses one replenishable encoded T resource with explicit static
    measurement branches and assumptions recorded in frontend_metadata.

    required-only inserts the SE required by S/Sdg. after-each-gate additionally
    inserts one ordinary SE per affected block after H/CZ/Pauli/identity gates.
    The policy is a compilation choice, not a fault-tolerance certification.
    The default bus backend calls Bloqade Lanes and measures only in the upper
    SLM zone. routing_backend="legacy" explicitly selects the historical
    arbitrary-move backend for reproducing earlier experiments.
    """
    from ftqc_patch_rotation.passes.lowering import compile_rotated_circuit
    from ftqc_patch_rotation.passes.transversal import lower_transversal
    from ftqc_patch_rotation.passes.frontend.transversal_input import prepare_transversal_input
    if se_policy not in ("required-only", "after-each-gate"):
        raise ValueError("unsupported transversal SE policy")
    if routing_backend not in {"legacy", "bloqade-lanes"}:
        raise ValueError("unsupported transversal routing backend")
    metadata = {}
    if isinstance(circuit, CompiledCircuit):
        if t_measurements is not None:
            raise ValueError("T branches must be selected before the logical DAG is compiled")
        compiled = circuit
    else:
        normalized, metadata = prepare_transversal_input(circuit, seed=seed, t_measurements=t_measurements)
        compiled = compile_rotated_circuit(normalized, optimizer, allow_resource_ops=bool(metadata))
    anchors = tuple(op.id for op in compiled.operations() if op.kind in {"h", "cz", "x", "y", "z", "id"}) if se_policy == "after-each-gate" else ()
    if routing_backend == "bloqade-lanes":
        from ftqc_patch_rotation.passes.bus_transversal import lower_bus_transversal
        program = lower_bus_transversal(compiled, processor, seed=seed, se_after_nodes=anchors, frontend_metadata=metadata)
    else:
        program = lower_transversal(compiled, processor, seed=seed, se_after_nodes=anchors, frontend_metadata=metadata)
    return compiled, program


def compile_timed_transversal(circuit, processor, optimizer=greedy_optimize, *, seed=0,
                              se_policy="required-only", timing_config=None, t_measurements=None,
                              scheduling="serial", routing_backend="bloqade-lanes"):
    """Return logical DAG, transversal IR and serial/parallel timing annotations."""
    from ftqc_patch_rotation.passes.timing import time_transversal
    compiled, program = compile_transversal(circuit, processor, optimizer, seed=seed,
                                          se_policy=se_policy, t_measurements=t_measurements, routing_backend=routing_backend)
    return compiled, program, time_transversal(compiled, processor, program, timing_config, scheduling=scheduling)
