"""Carrier-level Clifford lowering; physical trajectories remain abstract."""
from dataclasses import asdict, dataclass, replace

from ftqc_patch_rotation.codes import transversal_cz_pairs
from ftqc_patch_rotation.ir.rotation_macro import CodeBlockState, RotationMacro
from ftqc_patch_rotation.ir.se_circuit import ConventionalSEProgram, SEGate
from ftqc_patch_rotation.passes.se.rotated import compile_rotated_fold_s_round


@dataclass(frozen=True)
class RotatedCliffordStep:
    node_id: int
    logical_gate: str
    logical_qubits: tuple[int, ...]
    gates: tuple[SEGate, ...] = ()
    rotation: RotationMacro | None = None
    se: ConventionalSEProgram | None = None

    def to_dict(self):
        return {"node_id": self.node_id, "logical_gate": self.logical_gate,
                "logical_qubits": list(self.logical_qubits),
                "gates": [asdict(g) for g in self.gates],
                "rotation": self.rotation.to_dict() if self.rotation else None,
                "se": self.se.to_dict() if self.se else None}


@dataclass(frozen=True)
class RotatedCliffordProgram:
    initial_states: tuple[CodeBlockState, ...]
    steps: tuple[RotatedCliffordStep, ...]
    final_states: tuple[CodeBlockState, ...]
    next_measurement_offset: int
    next_round_indices: tuple[int, ...]

    def to_dict(self):
        return {"schema": "ftqc.rotated-clifford-program.v1",
                "implementation": "gate-circuits-with-abstract-rot",
                "initial_states": [s.to_dict() for s in self.initial_states],
                "steps": [s.to_dict() for s in self.steps],
                "final_states": [s.to_dict() for s in self.final_states],
                "next_measurement_offset": self.next_measurement_offset,
                "next_round_indices": list(self.next_round_indices)}


def lower_rotated_clifford(circuit, initial_states, check_carriers, backend, *,
                          measurement_offset=0, round_indices=None):
    """Lower a rotated-code DAG in deterministic topological order.

    Inputs are already encoded blocks, in the canonical initial frame expected
    by the pairing optimizer. Ancillas have fixed check roles. Only S/Sdg insert
    SE here; a general error-correction cadence is not selected by this pass.
    The output is a serial circuit trace, not a hardware timing schedule.
    """
    initial_states = tuple(initial_states)
    if len(initial_states) != circuit.num_qubits or set(check_carriers) != set(range(circuit.num_qubits)):
        raise ValueError("states and check mappings must cover every logical block")
    if isinstance(measurement_offset, bool) or not isinstance(measurement_offset, int) or measurement_offset < 0:
        raise ValueError("measurement offset must be a nonnegative integer")
    rounds = list((0,)*circuit.num_qubits if round_indices is None else round_indices)
    if len(rounds) != circuit.num_qubits or any(isinstance(i, bool) or not isinstance(i, int) or i < 0 for i in rounds):
        raise ValueError("one nonnegative round index per block is required")
    used = []
    for q, state in enumerate(initial_states):
        if state.representation.layout != backend.layout or state.representation.orientation:
            raise ValueError("initial blocks must use the backend layout in the canonical frame")
        state.representation.layout.validate()
        checks = check_carriers[q]
        if set(checks) != {c.id for c in backend.layout.checks}:
            raise ValueError("check mappings must cover exactly the layout checks")
        used.extend(state.carriers_by_site)
        used.extend(checks.values())
    if any(not isinstance(c, str) or not c for c in used) or len(used) != len(set(used)):
        raise ValueError("all data/check carriers must be nonempty and globally distinct")
    states, steps = list(initial_states), []
    offset = measurement_offset
    for op in circuit.operations():
        if op.kind not in {"rot", "h", "cz", "s", "sdg", "x", "y", "z", "id", "barrier"}:
            raise ValueError(f"unsupported rotated-code operation: {op.kind}")
        if any(isinstance(q, bool) or not isinstance(q, int) or not 0 <= q < circuit.num_qubits for q in op.qubits):
            raise ValueError("invalid logical operand")
        if len(set(op.qubits)) != len(op.qubits):
            raise ValueError("duplicate logical operand")
        if op.kind != "barrier" and len(op.qubits) != (2 if op.kind == "cz" else 1):
            raise ValueError("incorrect logical gate arity")
        gates, rotation, se = (), None, None
        if op.kind == "cz":
            a, b = (states[q] for q in op.qubits)
            pairs = transversal_cz_pairs(a.representation, b.representation)
            gates = (SEGate("cz", pairs=tuple((a.carriers_by_site[i], b.carriers_by_site[j]) for i, j in pairs)),)
        elif op.kind not in ("barrier", "id"):
            q = op.qubits[0]
            state = states[q]
            if op.kind == "rot":
                rotation = backend.lower(state)
                states[q] = rotation.after
            elif op.kind == "h":
                gates = (SEGate("h", state.carriers_by_site),)
                states[q] = replace(state, representation=state.representation.toggled())
            elif op.kind in ("s", "sdg"):
                se = compile_rotated_fold_s_round(state, check_carriers[q], inverse=op.kind == "sdg",
                    round_index=rounds[q], measurement_offset=offset)
                offset = se.next_measurement_offset
                rounds[q] += 1
            else:
                # X followed by Z represents logical Y up to an irrelevant global phase.
                gates = tuple(SEGate(basis, tuple(state.carriers_by_site[i] for i in support))
                    for basis, support in (("x", state.representation.logical_x), ("z", state.representation.logical_z))
                    if op.kind in (basis, "y"))
        steps.append(RotatedCliffordStep(op.id, op.kind, op.qubits, gates, rotation, se))
    return RotatedCliffordProgram(initial_states, tuple(steps), tuple(states), offset, tuple(rounds))
