"""Abstract ROT contracts; these records contain no executable atom paths."""
from dataclasses import dataclass
from fractions import Fraction

from ftqc_patch_rotation.codes import CodeRepresentation


@dataclass(frozen=True)
class ResourceRequirement:
    name: str
    units: int = 1

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("resource name must be nonempty")
        if isinstance(self.units, bool) or not isinstance(self.units, int) or self.units < 1:
            raise ValueError("resource units must be positive integers")


@dataclass(frozen=True)
class RotationModel:
    """User-supplied duration and resources reserved for the whole macro.

Names identify resource pools; this interface does not infer their capacities
or assume macros in the same instruction block can execute concurrently.
"""
    name: str
    duration_ns: Fraction
    resources: tuple[ResourceRequirement, ...]

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("rotation model name must be nonempty")
        if isinstance(self.duration_ns, bool) or not isinstance(self.duration_ns, (int, Fraction)) or self.duration_ns <= 0:
            raise ValueError("duration_ns must be a positive integer or Fraction")
        object.__setattr__(self, "duration_ns", Fraction(self.duration_ns))
        if not isinstance(self.resources, tuple) or not self.resources or any(
                not isinstance(r, ResourceRequirement) for r in self.resources):
            raise ValueError("explicit resource requirements are required")
        if len({r.name for r in self.resources}) != len(self.resources):
            raise ValueError("duplicate resource pool")

    def to_dict(self):
        return {"name": self.name, "duration_ns": str(self.duration_ns),
                "resources": [{"name": r.name, "units": r.units} for r in self.resources]}


@dataclass(frozen=True)
class CodeBlockState:
    representation: CodeRepresentation
    # Persistent carrier IDs, indexed by local topology site (not intrinsic qubit ID).
    carriers_by_site: tuple[str, ...]
    reset_epoch: int = 0

    def __post_init__(self):
        if not isinstance(self.carriers_by_site, tuple) or len(self.carriers_by_site) != len(self.representation.layout.data):
            raise ValueError("one carrier per data site is required")
        if any(not isinstance(c, str) or not c for c in self.carriers_by_site) or len(set(self.carriers_by_site)) != len(self.carriers_by_site):
            raise ValueError("carrier IDs must be nonempty and unique")
        if isinstance(self.reset_epoch, bool) or not isinstance(self.reset_epoch, int) or self.reset_epoch < 0:
            raise ValueError("reset_epoch must be a nonnegative integer")

    def to_dict(self):
        layout = self.representation.layout
        return {"code_kind": layout.code_kind, "distance": layout.distance,
                "convention": layout.convention, "orientation": self.representation.orientation,
                "carriers_by_site": list(self.carriers_by_site), "reset_epoch": self.reset_epoch}

    def rotated(self):
        """ZX-duality permutation with logical identity, independent of timing."""
        permutation = self.representation.layout.zx_permutation
        carriers = [None]*len(permutation)
        for source, destination in enumerate(permutation):
            carriers[destination] = self.carriers_by_site[source]
        return CodeBlockState(self.representation.toggled(), tuple(carriers), self.reset_epoch)

    @classmethod
    def from_dict(cls, value):
        from ftqc_patch_rotation.codes import rotated_surface_layout
        layout = rotated_surface_layout(value["distance"])
        if value["code_kind"] != layout.code_kind or value["convention"] != layout.convention:
            raise ValueError("unsupported code convention")
        return cls(CodeRepresentation(layout, value["orientation"]),
                   tuple(value["carriers_by_site"]), value["reset_epoch"])


@dataclass(frozen=True)
class RotationMacro:
    before: CodeBlockState
    after: CodeBlockState
    # Source site -> destination site; no physical coordinates or path implied.
    permutation: tuple[int, ...]
    model: RotationModel

    def validate(self):
        layout = self.before.representation.layout
        layout.validate()
        if self.permutation != layout.zx_permutation:
            raise ValueError("ROT must use the declared ZX-duality permutation")
        if self.after.representation != self.before.representation.toggled():
            raise ValueError("ROT must toggle the encoding frame")
        if self.after.reset_epoch != self.before.reset_epoch:
            raise ValueError("ROT cannot cross a reset epoch")
        expected = [None]*len(self.permutation)
        for source, destination in enumerate(self.permutation):
            expected[destination] = self.before.carriers_by_site[source]
        if tuple(expected) != self.after.carriers_by_site:
            raise ValueError("incorrect carrier permutation")

    def to_dict(self):
        self.validate()
        return {"schema": "ftqc.rotation-macro.v1", "implementation": "abstract",
                "logical_action": "identity", "before": self.before.to_dict(),
                "after": self.after.to_dict(), "permutation": list(self.permutation),
                "model": self.model.to_dict()}

    @classmethod
    def from_dict(cls, value):
        if value.get("schema") != "ftqc.rotation-macro.v1" or value.get("implementation") != "abstract" or value.get("logical_action") != "identity":
            raise ValueError("unsupported ROT macro contract")

        m = value["model"]
        model = RotationModel(m["name"], Fraction(m["duration_ns"]),
                              tuple(ResourceRequirement(**r) for r in m["resources"]))
        result = cls(CodeBlockState.from_dict(value["before"]), CodeBlockState.from_dict(value["after"]),
                     tuple(value["permutation"]), model)
        result.validate()
        return result
