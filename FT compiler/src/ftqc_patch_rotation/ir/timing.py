"""Configurable illustrative nanosecond costs and transversal timing records."""
from dataclasses import asdict, dataclass, field
import math

SERIAL_SCHEDULE = "serial; parallel operands inside each existing group"
PARALLEL_SCHEDULE = "parallel; exclusive operation classes; AOD non-crossing; one gate type"


def finite_nonnegative(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be a finite {'positive' if positive else 'nonnegative'} number")
    return float(value)


@dataclass(frozen=True)
class TimingConfig:
    """Defaults are research estimates, not hardware calibrations.

    One transversal group has one gate duration, independent of pair count.
    Move cost = move_ns_per_um * max(group Euclidean distance in micrometres).
    Overrides address leaf IDs s<step> or s<step>.a<action>.
    """
    gate_durations_ns: dict[str, float] = field(default_factory=lambda: {
        "h": 100.0, "x": 100.0, "y": 100.0, "z": 100.0,
        "s": 100.0, "sdg": 100.0, "cx": 200.0, "cz": 200.0,
        "reset": 1000.0, "measure": 2000.0, "id": 0.0,
        "prepare_t": 1000.0, "logical_measure_z": 2000.0})
    deformation_durations_ns: dict[str, float] = field(default_factory=lambda: {
        "rot90": 10000.0, "fold-diagonal": 5000.0, "unfold-diagonal": 5000.0})
    move_ns_per_um: float = 100.0
    start_time_ns: float = 0.0
    duration_overrides_ns: dict[str, float] = field(default_factory=dict)
    aod_count: int = 1

    def __post_init__(self):
        self.validate()
        for name in ("gate_durations_ns", "deformation_durations_ns", "duration_overrides_ns"):
            object.__setattr__(self, name, {k: float(v) for k, v in getattr(self, name).items()})

    def validate(self):
        if type(self.aod_count) is not int or self.aod_count < 1:
            raise ValueError("aod_count must be a positive integer")
        finite_nonnegative(self.move_ns_per_um, "move_ns_per_um", positive=True)
        finite_nonnegative(self.start_time_ns, "start_time_ns")
        for name in ("gate_durations_ns", "deformation_durations_ns", "duration_overrides_ns"):
            values = getattr(self, name)
            if not isinstance(values, dict) or any(not isinstance(k, str) or not k for k in values):
                raise ValueError(f"invalid {name}")
            for k, v in values.items():
                finite_nonnegative(v, f"{name}[{k}]")

    def to_dict(self):
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class TimedInstruction:
    id: str
    step_index: int
    action_index: int | None
    node_id: int | None
    kind: str
    name: str
    blocks: tuple[int, ...]
    start_time: float
    duration: float
    end_time: float
    distance_um: float | None
    instruction: dict
    predecessors: tuple[str, ...] = ()
    aod_id: int | None = None


@dataclass(frozen=True)
class TimedStep:
    step_index: int
    kind: str
    node_id: int | None
    logical_gate: str | None
    start_time: float
    duration: float
    end_time: float
    instruction_ids: tuple[str, ...]


@dataclass(frozen=True)
class TimedTransversalProgram:
    config: TimingConfig
    steps: tuple[TimedStep, ...]
    instructions: tuple[TimedInstruction, ...]
    start_time: float
    duration: float
    end_time: float
    schedule_kind: str = SERIAL_SCHEDULE

    def to_dict(self):
        return {"schema": "ftqc.transversal-timing.v1", "time_unit": "ns", "distance_unit": "um",
                "aod_allocation": "exclusive-per-operation",
                "schedule_kind": self.schedule_kind,
                "calibration": "illustrative configurable defaults",
                "config": self.config.to_dict(), "steps": [asdict(s) for s in self.steps],
                "instructions": [asdict(i) for i in self.instructions],
                "start_time": self.start_time, "duration": self.duration, "end_time": self.end_time}

    @classmethod
    def from_dict(cls, value):
        if (value.get("schema") != "ftqc.transversal-timing.v1" or value.get("time_unit") != "ns"
                or value.get("distance_unit") != "um"
                or value.get("schedule_kind") not in {SERIAL_SCHEDULE, PARALLEL_SCHEDULE}
                or value.get("calibration") != "illustrative configurable defaults"):
            raise ValueError("unsupported transversal timing")
        return cls(TimingConfig(**value["config"]),
            tuple(TimedStep(**{**s, "instruction_ids": tuple(s["instruction_ids"])}) for s in value["steps"]),
            tuple(TimedInstruction(**{**i, "blocks": tuple(i["blocks"]), "predecessors": tuple(i.get("predecessors", ())),
                "aod_id": i.get("aod_id") if value.get("aod_allocation") else
                    (0 if i["kind"] in {"block_move", "block_offset"} else None)}) for i in value["instructions"]),
            value["start_time"], value["duration"], value["end_time"], value["schedule_kind"])
