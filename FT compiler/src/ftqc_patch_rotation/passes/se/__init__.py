"""SE motion passes and reserved block-transfer interface.

ENTANGLE and role exchange are semantic macros, not a physical gate decomposition.
"""
from ftqc_patch_rotation.ir.se import SEProgram
from .layout import make_se_state, validate_restored
from .planning import plan_layer
from .validation import apply_instruction, validate_se_program


def compile_stabilizer_measurement(processor, data_patch=None, ancilla_patch=None,
                                   *, initial_state=None, swap_directions=("D",)):
    """Compile one LRUD motion round for a non-rotated surface-code block.

    Accept a restored previous final state to preserve atom identities across rounds.
    State preparation, readout, Pauli frames and gate-level role-transfer lowering
    are outside this motion pass's contract.
    """
    if initial_state is not None:
        if data_patch is not None or ancilla_patch is not None:
            raise ValueError("pass initial_state or patch names, not both")
        state = initial_state.copy()
    else:
        if data_patch is None or ancilla_patch is None:
            raise ValueError("both DQ and AQ patch names are required")
        state = make_se_state(processor, data_patch, ancilla_patch)
    validate_restored(processor, state)
    swaps = tuple(swap_directions)
    if len(set(swaps)) != len(swaps) or not set(swaps) <= set("LRUD"):
        raise ValueError("invalid swap directions")
    program = SEProgram(processor.config.d, state.copy(), swap_directions=swaps)
    for direction in "LRUD":
        layer = plan_layer(processor, state, direction, direction in swaps)
        for op in layer.instructions:
            apply_instruction(processor, state, op)
            program.instructions.append(op)
        validate_restored(processor, state)
    validate_se_program(processor, program)
    return program


def compile_block_transfer(processor, state, target_pair):
    """Reserved: teleport an encoded state to a new block, including its frame."""
    raise NotImplementedError("SE transfer to a new code block is reserved; not implemented")


__all__ = ["compile_stabilizer_measurement", "compile_block_transfer", "make_se_state",
           "plan_layer", "validate_se_program"]
