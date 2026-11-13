"""Atom-level SE motion IR; atom identity is independent of its current role."""
from dataclasses import dataclass, field
from fractions import Fraction


@dataclass(frozen=True)
class SEAtom:
    id: str
    role: str
    x: Fraction
    y: Fraction

    def to_dict(self):
        return dict(id=self.id, role=self.role, x=str(self.x), y=str(self.y))


@dataclass(frozen=True)
class SEInstruction:
    kind: str
    direction: str
    name: str
    atoms: tuple[str, ...] = ()
    delta: tuple[Fraction, Fraction] = (Fraction(0), Fraction(0))
    pairs: tuple[tuple[str, str], ...] = ()  # (current D, current A)

    def to_dict(self):
        return dict(kind=self.kind, direction=self.direction, name=self.name,
                    atoms=list(self.atoms), delta=[str(v) for v in self.delta],
                    pairs=[list(p) for p in self.pairs])


@dataclass
class SEState:
    atoms: dict[str, SEAtom]
    data_patch: str
    ancilla_patch: str

    def copy(self):
        return SEState(self.atoms.copy(), self.data_patch, self.ancilla_patch)

    def to_dict(self):
        return dict(data_patch=self.data_patch, ancilla_patch=self.ancilla_patch,
                    atoms=[a.to_dict() for a in self.atoms.values()])


@dataclass
class SEProgram:
    distance: int
    initial: SEState
    instructions: list[SEInstruction] = field(default_factory=list)
    swap_directions: tuple[str, ...] = ("D",)

    @property
    def aod_stages(self):
        return sum(op.kind == "aod" for op in self.instructions)

    def to_dict(self):
        return dict(schema="ftqc.se-motion.v1", distance=self.distance,
                    swap_directions=list(self.swap_directions), initial=self.initial.to_dict(),
                    instructions=[op.to_dict() for op in self.instructions])

    @classmethod
    def from_dict(cls, value):
        if value.get("schema") != "ftqc.se-motion.v1":
            raise ValueError("unsupported SE motion schema")
        initial = value["initial"]
        atoms = [SEAtom(a["id"], a["role"], Fraction(a["x"]), Fraction(a["y"]))
                 for a in initial["atoms"]]
        if len({a.id for a in atoms}) != len(atoms):
            raise ValueError("duplicate atom id")
        instructions = [SEInstruction(o["kind"], o["direction"], o["name"],
                                     tuple(o["atoms"]), tuple(Fraction(v) for v in o["delta"]),
                                     tuple(tuple(p) for p in o["pairs"])) for o in value["instructions"]]
        return cls(value["distance"], SEState({a.id: a for a in atoms},
                   initial["data_patch"], initial["ancilla_patch"]), instructions,
                   tuple(value["swap_directions"]))
