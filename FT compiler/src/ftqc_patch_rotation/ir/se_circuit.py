"""Rotated-code ordinary and mid-cycle fold syndrome circuits, without motion."""
from dataclasses import asdict, dataclass

from ftqc_patch_rotation.ir.rotation_macro import CodeBlockState


@dataclass(frozen=True)
class SEGate:
    kind: str
    targets: tuple[str, ...] = ()
    pairs: tuple[tuple[str, str], ...] = ()  # ordered (control, target)


@dataclass(frozen=True)
class SEReadout:
    record_index: int  # absolute index in the caller's measurement stream
    round_index: int
    reset_epoch: int  # logical epoch; not a physical reset generation
    check_id: int
    basis: str
    check_carrier: str
    data_support: tuple[str, ...]


def conventional_instructions(state, check_carriers):
    """Keep canonical hook order; the dual frame reverses each CX direction."""
    rep = state.representation
    carrier = dict(enumerate(state.carriers_by_site))
    carrier.update((c.id, a) for c, a in zip(rep.checks, check_carriers))
    xs = tuple(carrier[c.id] for c in rep.checks if c.basis == "X")
    result = [SEGate("reset", check_carriers), SEGate("h", xs)]
    for layer in rep.layout.interaction_layers:
        pairs = tuple((carrier[t], carrier[c]) if rep.orientation else (carrier[c], carrier[t])
                      for c, t in layer)
        result.append(SEGate("cx", pairs=pairs))
    result.extend((SEGate("h", xs), SEGate("measure", check_carriers)))
    return tuple(result)


def fold_instructions(state, check_carriers, logical_gate):
    """Diagonal mid-cycle fold; boundary checks do not participate."""
    if logical_gate not in ("s", "sdg"):
        raise ValueError("fold logical gate must be s or sdg")
    layout = state.representation.layout
    if layout.distance not in (3, 5, 7, 9):
        raise ValueError("fold-S is currently certified only for distances 3, 5, 7, 9")
    carriers = dict(enumerate(state.carriers_by_site))
    carriers.update((c.id, a) for c, a in zip(layout.checks, check_carriers))
    bulk = {(q.x, q.y): q.id for q in (*layout.data, *layout.checks)
            if 1 <= q.x <= 2*layout.distance-1 and 1 <= q.y <= 2*layout.distance-1}
    pairs, data, checks = [], [], []
    for (x, y), q in sorted(bulk.items()):
        if x == y:
            (data if q < len(layout.data) else checks).append(carriers[q])
        elif x < y:
            pairs.append((carriers[q], carriers[bulk[y, x]]))
    fold = (SEGate("cz", pairs=tuple(pairs)), SEGate(logical_gate, tuple(data)),
            SEGate("sdg" if logical_gate == "s" else "s", tuple(checks)))
    ordinary = conventional_instructions(state, check_carriers)
    return ordinary[:4] + fold + ordinary[4:]


@dataclass(frozen=True)
class ConventionalSEProgram:
    initial_state: CodeBlockState
    # In layout.checks order. These remain check carriers throughout the round.
    check_carriers: tuple[str, ...]
    round_index: int
    measurement_offset: int
    instructions: tuple[SEGate, ...]
    measurements: tuple[SEReadout, ...]
    logical_gate: str = "id"

    @property
    def protocol(self):
        return "conventional-four-layer-v1" if self.logical_gate == "id" else "mid-cycle-diagonal-fold-v1"

    @property
    def final_state(self):
        """Carrier locations/frame are unchanged; quantum state is projected."""
        return self.initial_state

    @property
    def next_measurement_offset(self):
        return self.measurement_offset + len(self.measurements)

    def validate(self):
        state = self.initial_state
        state.representation.layout.validate()
        for index in (self.round_index, self.measurement_offset):
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise ValueError("round and measurement indices must be nonnegative integers")
        checks = state.representation.checks
        if not isinstance(self.check_carriers, tuple) or len(self.check_carriers) != len(checks):
            raise ValueError("one carrier per check is required")
        if any(not isinstance(a, str) or not a for a in self.check_carriers) or len(set(self.check_carriers)) != len(checks):
            raise ValueError("check carriers must be nonempty and unique")
        if set(self.check_carriers) & set(state.carriers_by_site):
            raise ValueError("data and check carriers must be disjoint")
        if self.logical_gate not in ("id", "s", "sdg"):
            raise ValueError("unsupported SE logical gate")
        expected_instructions = (conventional_instructions(state, self.check_carriers)
            if self.logical_gate == "id" else fold_instructions(state, self.check_carriers, self.logical_gate))
        if self.instructions != expected_instructions:
            raise ValueError("instructions disagree with the declared SE protocol")
        if len(self.measurements) != len(checks):
            raise ValueError("incorrect number of measurement records")
        for i, (check, record) in enumerate(zip(checks, self.measurements)):
            expected = SEReadout(self.measurement_offset+i, self.round_index, state.reset_epoch,
                check.id, check.basis, self.check_carriers[i],
                tuple(state.carriers_by_site[q] for q in check.support))
            if record != expected:
                raise ValueError("measurement record disagrees with its check")

    def to_dict(self):
        self.validate()
        return {"schema": "ftqc.rotated-se-circuit.v1", "protocol": self.protocol,
                "logical_gate": self.logical_gate,
                "implementation": "gate-circuit", "initial_state": self.initial_state.to_dict(),
                "check_carriers": list(self.check_carriers), "round_index": self.round_index,
                "measurement_offset": self.measurement_offset,
                "instructions": [asdict(op) for op in self.instructions],
                "measurements": [asdict(m) for m in self.measurements]}

    @classmethod
    def from_dict(cls, value):
        if (value.get("schema") != "ftqc.rotated-se-circuit.v1"
                or value.get("protocol") not in ("conventional-four-layer-v1", "mid-cycle-diagonal-fold-v1")
                or value.get("implementation") != "gate-circuit"):
            raise ValueError("unsupported rotated SE circuit")
        instructions = tuple(SEGate(o["kind"], tuple(o["targets"]), tuple(tuple(p) for p in o["pairs"]))
                             for o in value["instructions"])
        measurements = tuple(SEReadout(**{**m, "data_support": tuple(m["data_support"])})
                             for m in value["measurements"])
        result = cls(CodeBlockState.from_dict(value["initial_state"]), tuple(value["check_carriers"]),
                     value["round_index"], value["measurement_offset"], instructions, measurements,
                     value.get("logical_gate", "id"))
        result.validate()
        if result.protocol != value["protocol"]:
            raise ValueError("SE protocol and logical gate disagree")
        return result

    def to_stim(self, wire_map=None):
        """Export an appendable round. Stim is an optional validation dependency.

        The caller prepares data and composes measurement/detector context.
        No initialization, data measurement, noise or detectors are added.
        """
        import stim
        self.validate()
        carriers = self.initial_state.carriers_by_site + self.check_carriers
        if wire_map is None:
            wire_map = dict(zip(carriers, range(len(carriers))))
        if not set(carriers) <= set(wire_map):
            raise ValueError("wire map must cover all data and check carriers")
        wires = [wire_map[c] for c in carriers]
        if any(isinstance(w, bool) or not isinstance(w, int) or w < 0 for w in wires) or len(set(wires)) != len(wires):
            raise ValueError("wire map must assign distinct nonnegative integer wires")
        circuit = stim.Circuit()
        names = {"reset": "R", "h": "H", "cx": "CX", "cz": "CZ", "s": "S", "sdg": "S_DAG", "measure": "M"}
        for op in self.instructions:
            targets = [wire_map[q] for pair in op.pairs for q in pair] if op.kind in ("cx", "cz") else [wire_map[q] for q in op.targets]
            if targets:
                circuit.append(names[op.kind], targets)
            circuit.append("TICK")
        return circuit
