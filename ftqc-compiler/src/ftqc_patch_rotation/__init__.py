"""Patch-rotation optimization for transversal Clifford circuits."""

from .model import GateNode, PreparedCircuit
from .preprocess import preprocess
from .simulator import SimulationResult, simulate_rotations
from .greedy import greedy_optimize
from .sat import SatTimeoutError, sat_optimize
from .trivial import trivial_optimize
from .window_sat import sliding_window_sat_optimize
from .compiler import CompiledCircuit, CompiledNode, build_compiled_dag, compile_circuit
from .hardware import Processor, ProcessorConfig
from .pipeline import compile_processor, save_compilation, load_compilation
from .routing import RoutingError, route_and_schedule, validate_schedule

__all__ = [
    "GateNode",
    "PreparedCircuit",
    "SimulationResult",
    "SatTimeoutError",
    "greedy_optimize",
    "preprocess",
    "sat_optimize",
    "simulate_rotations",
    "trivial_optimize",
    "sliding_window_sat_optimize",
    "CompiledCircuit",
    "CompiledNode",
    "build_compiled_dag",
    "compile_circuit",
    "Processor",
    "ProcessorConfig",
    "compile_processor",
    "save_compilation",
    "load_compilation",
    "RoutingError",
    "route_and_schedule",
    "validate_schedule",
]
