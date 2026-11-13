"""Lower existing ROT nodes into explicit, timed abstract permutation records.

Patch routing is replayed first. Resulting records annotate that schedule;
they do not change trap geometry, place SE rounds or schedule resource time.
"""
from dataclasses import dataclass, replace

from ftqc_patch_rotation.codes import CodeRepresentation, RotatedSurfaceLayout, transversal_cz_pairs
from ftqc_patch_rotation.ir.rotation_macro import CodeBlockState, RotationMacro, RotationModel
from ftqc_patch_rotation.passes.routing.validation import validate_schedule


@dataclass(frozen=True)
class AbstractRotationBackend:
    layout: RotatedSurfaceLayout
    model: RotationModel

    def __post_init__(self):
        self.layout.validate()
        if not isinstance(self.model, RotationModel):
            raise ValueError("a rotation duration/resource model is required")

    def lower(self, state: CodeBlockState) -> RotationMacro:
        if state.representation.layout != self.layout:
            raise ValueError("backend and code block layouts disagree")
        p = self.layout.zx_permutation
        after = state.rotated()
        result = RotationMacro(state, after, p, self.model)
        result.validate()
        return result


@dataclass(frozen=True)
class AnchoredRotation:
    node_id: int
    logical_qubit: int
    block_index: int
    patch: str
    macro: RotationMacro

    def to_dict(self):
        return {"node_id": self.node_id, "logical_qubit": self.logical_qubit,
                "block_index": self.block_index, "patch": self.patch,
                "macro": self.macro.to_dict()}


@dataclass(frozen=True)
class RotationMacroTrace:
    rotations: tuple[AnchoredRotation, ...]
    final_states: tuple[CodeBlockState, ...]

    @property
    def serial_rotation_duration_ns(self):
        """Sum of macro durations only, not a circuit makespan."""
        return sum((r.macro.model.duration_ns for r in self.rotations), start=0)

    def to_dict(self):
        return {"schema": "ftqc.rotation-macro-trace.v1", "implementation": "abstract",
                "serial_rotation_duration_ns": str(self.serial_rotation_duration_ns),
                "rotations": [r.to_dict() for r in self.rotations],
                "final_states": [s.to_dict() for s in self.final_states]}


def lower_rot_macros(circuit, processor, schedule, backend: AbstractRotationBackend,
                     *, initial_carriers=None) -> RotationMacroTrace:
    """Annotate a validated schedule, currently for the H/CZ/Pauli subset.

When carrier IDs are omitted, generated IDs are symbolic; they are not a
claim that a physical initial placement or state preparation has been built.
Reset follows the existing canonical-frame convention and retains carrier
locations. Epochs refer to logical resets, not physical atom generations.
"""
    validate_schedule(circuit, processor, schedule)
    if processor.config.d != backend.layout.distance:
        raise ValueError("processor and code distances disagree")
    supported = {"rot", "h", "cz", "x", "y", "z", "id", "reset", "measure", "barrier"}
    if any(op.kind not in supported for op in circuit.operations()):
        raise ValueError("rotated macro annotation supports H/CZ/Pauli only; use lower_rotated_clifford for S/SE")
    n = len(backend.layout.data)
    if initial_carriers is None:
        initial_carriers = {q: tuple(f"q{q}:carrier{i}" for i in range(n)) for q in range(circuit.num_qubits)}
    if set(initial_carriers) != set(range(circuit.num_qubits)):
        raise ValueError("initial carriers must cover every logical block")
    states = [CodeBlockState(CodeRepresentation(backend.layout), tuple(initial_carriers[q]))
              for q in range(circuit.num_qubits)]
    all_carriers = [c for s in states for c in s.carriers_by_site]
    if len(all_carriers) != len(set(all_carriers)):
        raise ValueError("physical carriers cannot be shared between blocks")
    positions = schedule.mapping.initial_data_patch.copy()
    records = []
    for index, block in enumerate(schedule.blocks):
        for move in block.moves:
            positions[move.qubit] = move.target
        for node_id in block.nodes:
            op = circuit.operation(node_id)
            if op.kind == "rot":
                q = op.qubits[0]
                macro = backend.lower(states[q])
                records.append(AnchoredRotation(node_id, q, index, positions[q], macro))
                states[q] = macro.after
            elif op.kind == "h":
                q = op.qubits[0]
                states[q] = replace(states[q], representation=states[q].representation.toggled())
            elif op.kind == "reset":
                q = op.qubits[0]
                states[q] = replace(states[q], representation=CodeRepresentation(backend.layout),
                                    reset_epoch=states[q].reset_epoch+1)
            elif op.kind == "cz":
                a, b = op.qubits
                transversal_cz_pairs(states[a].representation, states[b].representation)
    return RotationMacroTrace(tuple(records), tuple(states))
