"""Block movement, deformation and transversal operations; no atom paths."""
from dataclasses import asdict, dataclass, field

from ftqc_patch_rotation.ir.routing import Mapping, Move


@dataclass(frozen=True)
class TransversalAction:
    kind: str
    blocks: tuple[int, ...] = ()
    gate: str | None = None
    targets: tuple[tuple[int, int], ...] = ()  # block ID, local topology site
    pairs: tuple[tuple[tuple[int, int], tuple[int, int]], ...] = ()
    offset: tuple[int, int] | None = None  # absolute code-lattice/site-pitch offset
    layer: int | None = None
    deformation: str | None = None
    permutation: tuple[int, ...] = ()
    assumed_result: int | None = None

    @classmethod
    def from_dict(cls, value):
        return cls(value["kind"], tuple(value["blocks"]), value["gate"],
                   tuple(tuple(t) for t in value["targets"]),
                   tuple(tuple(tuple(t) for t in p) for p in value["pairs"]),
                   tuple(value["offset"]) if value["offset"] is not None else None,
                   value["layer"], value["deformation"], tuple(value["permutation"]), value.get("assumed_result"))


@dataclass(frozen=True)
class TransversalStep:
    kind: str
    moves: tuple[Move, ...] = ()  # qubit is a block ID: data=2q, checks=2q+1
    node_id: int | None = None
    logical_gate: str | None = None
    actions: tuple[TransversalAction, ...] = ()
    round_index: int | None = None
    measurement_offset: int | None = None
    # Global measurement record index, local check ID, represented check basis.
    readouts: tuple[tuple[int, int, str], ...] = ()
    logical_qubit: int | None = None
    transport: dict = field(default_factory=dict)

    def to_dict(self):
        result = asdict(self)
        if not self.transport:
            result.pop("transport")
        return result

    @classmethod
    def from_dict(cls, value):
        return cls(value["kind"], tuple(Move(**m) for m in value["moves"]),
                   value["node_id"], value["logical_gate"],
                   tuple(TransversalAction.from_dict(a) for a in value["actions"]),
                   value["round_index"], value["measurement_offset"],
                   tuple(tuple(r) for r in value["readouts"]), value["logical_qubit"], value.get("transport", {}))


@dataclass(frozen=True)
class TransversalProgram:
    mapping: Mapping
    steps: tuple[TransversalStep, ...]
    final_positions: dict[int, str]
    final_orientation: tuple[bool, ...]
    final_data_permutations: tuple[tuple[int, ...], ...]
    next_measurement_offset: int
    next_round_indices: tuple[int, ...]
    se_after_nodes: tuple[int, ...] = ()
    frontend_metadata: dict = field(default_factory=dict)
    se_offset_mode: str = "per-check"
    transport_mode: str = "free"
    transport_topology: dict = field(default_factory=dict)
    backend_metadata: dict = field(default_factory=dict)

    @property
    def schema_version(self):
        if self.transport_mode not in {"free", "bloqade-lanes"}:
            raise ValueError("unsupported transversal transport mode")
        return 4 if self.transport_mode == "bloqade-lanes" else 3 if self.se_offset_mode == "per-check" else 2

    def to_dict(self):
        if self.se_offset_mode not in {"whole-block", "per-check"}:
            raise ValueError("unsupported SE offset mode")
        result = {"schema": f"ftqc.transversal-program.v{self.schema_version}", "code_kind": "rotated_surface",
                "block_ids": "data=2*q; check-ancilla=2*q+1",
                "storage_layout": "co-located data/check sites in one patch per logical code",
                "offset_units": "code-lattice; one unit = one patch site pitch",
                "mapping": asdict(self.mapping), "steps": [s.to_dict() for s in self.steps],
                "final_positions": self.final_positions,
                "final_orientation": self.final_orientation,
                "final_data_permutations": self.final_data_permutations,
                "next_measurement_offset": self.next_measurement_offset,
                "next_round_indices": self.next_round_indices,
                "se_after_nodes": self.se_after_nodes, "frontend_metadata": self.frontend_metadata}
        if self.se_offset_mode == "per-check":
            result["offset_scope"] = "explicit check-site selectors"
        if self.transport_mode == "bloqade-lanes":
            result.update(transport_mode=self.transport_mode, transport_topology=self.transport_topology,
                          backend_metadata=self.backend_metadata)
        return result

    @classmethod
    def from_dict(cls, value):
        if (value.get("schema") not in {"ftqc.transversal-program.v2", "ftqc.transversal-program.v3", "ftqc.transversal-program.v4"}
                or value.get("code_kind") != "rotated_surface"
                or value.get("block_ids") != "data=2*q; check-ancilla=2*q+1"
                or value.get("storage_layout") != "co-located data/check sites in one patch per logical code"
                or value.get("offset_units") != "code-lattice; one unit = one patch site pitch"):
            raise ValueError("unsupported transversal IR")
        selective = value["schema"] != "ftqc.transversal-program.v2"
        if selective and value.get("offset_scope") != "explicit check-site selectors":
            raise ValueError("unsupported SE offset scope")
        bus = value["schema"] == "ftqc.transversal-program.v4"
        if bus and value.get("transport_mode") != "bloqade-lanes":
            raise ValueError("unsupported bus transport mode")
        mapping = Mapping(**{k: {int(q): p for q, p in v.items()} for k, v in value["mapping"].items()})
        return cls(mapping, tuple(TransversalStep.from_dict(s) for s in value["steps"]),
                   {int(q): p for q, p in value["final_positions"].items()},
                   tuple(value["final_orientation"]),
                   tuple(tuple(p) for p in value["final_data_permutations"]),
                   value["next_measurement_offset"], tuple(value["next_round_indices"]),
                   tuple(value["se_after_nodes"]), value.get("frontend_metadata", {}),
                   "per-check" if selective else "whole-block", "bloqade-lanes" if bus else "free",
                   value.get("transport_topology", {}) if bus else {}, value.get("backend_metadata", {}) if bus else {})
