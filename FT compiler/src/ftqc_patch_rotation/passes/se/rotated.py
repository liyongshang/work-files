"""Build a conventional syndrome round on an existing encoded data block."""
from dataclasses import replace
from ftqc_patch_rotation.ir.se_circuit import ConventionalSEProgram, SEReadout, conventional_instructions, fold_instructions


def compile_rotated_se_round(state, check_carriers, *, round_index=0, measurement_offset=0):
    """Require explicit check-ID -> carrier mapping; never reset the data.

    Physical meeting positions, durations, error correction and a policy for
    inserting rounds in the logical program are outside this circuit pass.
    """
    checks = state.representation.checks
    if any(isinstance(i, bool) or not isinstance(i, int) or i < 0 for i in (round_index, measurement_offset)):
        raise ValueError("round and measurement indices must be nonnegative integers")
    if set(check_carriers) != {c.id for c in checks}:
        raise ValueError("check carrier mapping must cover exactly the layout checks")
    carriers = tuple(check_carriers[c.id] for c in checks)
    # Validate the complete carrier, record and circuit contract before returning.
    records = tuple(SEReadout(measurement_offset+i, round_index, state.reset_epoch,
        c.id, c.basis, carriers[i], tuple(state.carriers_by_site[q] for q in c.support))
        for i, c in enumerate(checks))
    result = ConventionalSEProgram(state, carriers, round_index, measurement_offset,
                                   conventional_instructions(state, carriers), records)
    result.validate()
    return result


def compile_rotated_fold_s_round(state, check_carriers, *, inverse=False,
                                round_index=0, measurement_offset=0):
    """An S/Sdg round with explicit ancilla reset and readout.

    Both ZX representations are supported without ROT. This ideal circuit
    does not supply noise, detectors, decoding or physical movement paths.
    """
    if not isinstance(inverse, bool):
        raise ValueError("inverse must be a bool")
    ordinary = compile_rotated_se_round(state, check_carriers,
        round_index=round_index, measurement_offset=measurement_offset)
    gate = "sdg" if inverse else "s"
    result = replace(ordinary, logical_gate=gate,
                     instructions=fold_instructions(state, ordinary.check_carriers, gate))
    result.validate()
    return result
