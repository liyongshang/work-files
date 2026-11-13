"""Patch mapping and hardware instruction IR."""
from dataclasses import asdict, dataclass

@dataclass(frozen=True)
class Move:
    qubit: int
    start: str
    target: str


@dataclass
class Mapping:
    initial_data_patch: dict[int, str]
    ancilla_patch: dict[int, str]


@dataclass
class InstructionBlock:
    kind: str
    nodes: tuple[int, ...] = ()
    moves: tuple[Move, ...] = ()


@dataclass
class RoutingSchedule:
    mapping: Mapping
    blocks: list[InstructionBlock]
    cz_blocks: tuple[tuple[int, ...], ...]
    final_positions: dict[int, str]
    seed: int
    cost: float

    @property
    def stage_count(self):
        return sum(b.kind == "aod" for b in self.blocks)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        mapping = Mapping(**{k: {int(q): p for q, p in v.items()} for k, v in data["mapping"].items()})
        blocks = [InstructionBlock(b["kind"], tuple(b["nodes"]), tuple(Move(**m) for m in b["moves"]))
                  for b in data["blocks"]]
        return cls(mapping, blocks, tuple(tuple(b) for b in data["cz_blocks"]),
                   {int(q): p for q, p in data["final_positions"].items()}, data["seed"], data["cost"])
