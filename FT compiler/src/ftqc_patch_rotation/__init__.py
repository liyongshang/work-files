"""Patch-rotation optimization for transversal Clifford circuits."""

from ftqc_patch_rotation.ir.rotation import GateNode, PreparedCircuit
from ftqc_patch_rotation.passes.patch_rotation.preprocess import preprocess
from ftqc_patch_rotation.passes.patch_rotation.simulator import SimulationResult, simulate_rotations
from ftqc_patch_rotation.passes.patch_rotation.greedy import greedy_optimize
from ftqc_patch_rotation.passes.patch_rotation.sat import SatTimeoutError, sat_optimize
from ftqc_patch_rotation.passes.patch_rotation.trivial import trivial_optimize
from ftqc_patch_rotation.passes.patch_rotation.window_sat import sliding_window_sat_optimize
from ftqc_patch_rotation.ir.logical import CompiledCircuit, CompiledNode
from ftqc_patch_rotation.passes.lowering import build_compiled_dag, compile_circuit, compile_rotated_circuit
from ftqc_patch_rotation.hardware import Processor, ProcessorConfig
from ftqc_patch_rotation.bus_architecture import BusTopology, PatchBus
from ftqc_patch_rotation.pipeline import compile_processor, compile_se_round
from ftqc_patch_rotation.serialization import save_compilation, load_compilation
from ftqc_patch_rotation.passes.routing import RoutingError, route_and_schedule, validate_schedule
from ftqc_patch_rotation.ir.rotation_macro import CodeBlockState, ResourceRequirement, RotationModel, RotationMacro
from ftqc_patch_rotation.passes.rotation_macros import AbstractRotationBackend, lower_rot_macros
from ftqc_patch_rotation.ir.se_circuit import ConventionalSEProgram
from ftqc_patch_rotation.passes.se.rotated import compile_rotated_se_round, compile_rotated_fold_s_round
from ftqc_patch_rotation.passes.rotated_clifford import lower_rotated_clifford, RotatedCliffordProgram
from ftqc_patch_rotation.pipeline import compile_transversal
from ftqc_patch_rotation.ir.transversal import TransversalProgram
from ftqc_patch_rotation.passes.transversal_validation import validate_transversal
from ftqc_patch_rotation.serialization import save_transversal, load_transversal
from ftqc_patch_rotation.ir.timing import TimingConfig, TimedTransversalProgram
from ftqc_patch_rotation.passes.timing import time_transversal, validate_transversal_timing
from ftqc_patch_rotation.pipeline import compile_timed_transversal
from ftqc_patch_rotation.serialization import save_timed_transversal, load_timed_transversal

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
    "compile_rotated_circuit",
    "Processor",
    "ProcessorConfig",
    "BusTopology",
    "PatchBus",
    "compile_processor",
    "compile_se_round",
    "save_compilation",
    "load_compilation",
    "RoutingError",
    "route_and_schedule",
    "validate_schedule",
    "CodeBlockState",
    "ResourceRequirement",
    "RotationModel",
    "RotationMacro",
    "AbstractRotationBackend",
    "lower_rot_macros",
    "ConventionalSEProgram",
    "compile_rotated_se_round",
    "compile_rotated_fold_s_round",
    "lower_rotated_clifford",
    "RotatedCliffordProgram",
    "compile_transversal",
    "TransversalProgram",
    "validate_transversal",
    "save_transversal",
    "load_transversal",
    "TimingConfig",
    "TimedTransversalProgram",
    "time_transversal",
    "validate_transversal_timing",
    "compile_timed_transversal",
    "save_timed_transversal",
    "load_timed_transversal",
]
