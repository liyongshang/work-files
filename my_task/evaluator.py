"""Evaluate extra ROT counts using FT compiler's independent replay.

Run locally (no model/API needed):
    python evaluator.py init_program.py

FT_COMPILER_ROOT points to the FT compiler repository, not its src directory.
FT_ZX_SUITE=small (default), feynman_all, or qasm (FT_ZX_QASM_PATH required).
FT_ZX_SPLIT=search (default) or validation; never compare different splits.
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import numbers
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import tempfile
import time


TIMEOUT_SECONDS = float(os.environ.get("EVALUATOR_TIMEOUT_SECONDS", "90"))
SOLVER_TIMEOUT_SECONDS = float(os.environ.get("FT_ZX_SOLVER_TIMEOUT_SECONDS", "60"))
MEMORY_LIMIT_MB = int(os.environ.get("FT_ZX_MEMORY_LIMIT_MB", "2048"))
MAX_RESULT_BYTES = 8 * 1024 * 1024
_WINDOWS_JOB = None

SEARCH_QASM = (
    "tof_3.qasm", "barenco_tof_3.qasm", "mod5_4.qasm", "tof_4.qasm",
    "mod_mult_55.qasm", "vbe_adder_3.qasm",
)
VALIDATION_QASM = (
    "tof_5.qasm", "barenco_tof_4.qasm", "barenco_tof_5.qasm",
    "csla_mux_3.qasm", "gf2^4_mult.qasm", "rc_adder_6.qasm",
)
RANDOM_SIZES = ((4, 16), (8, 32), (12, 64), (20, 96))


def _configure_compiler() -> Path:
    configured = os.environ.get("FT_COMPILER_ROOT")
    # Default local layout: work/AI/SimpleTES and work/naqc/FT compiler.
    simpletes_root = Path(__file__).resolve().parents[3]
    default_root = simpletes_root.parent.parent / "naqc" / "FT compiler"
    root = Path(configured).expanduser().resolve() if configured else default_root
    if not (root / "src" / "ftqc_patch_rotation").is_dir():
        raise FileNotFoundError(
            "Set FT_COMPILER_ROOT to the FT compiler repository containing "
            "src/ftqc_patch_rotation and benchmarks/feynman_clifford. "
            f"Checked: {root}"
        )
    sys.path.insert(0, str(root / "src"))
    return root


def _build_cases(root: Path):
    from qiskit import qasm2
    from ftqc_patch_rotation.experiments.generator import random_layered_clifford_circuit
    from ftqc_patch_rotation.passes.patch_rotation.preprocess import preprocess

    suite = os.environ.get("FT_ZX_SUITE", "small")
    split = os.environ.get("FT_ZX_SPLIT", "search")
    if split not in {"search", "validation"}:
        raise ValueError("FT_ZX_SPLIT must be search or validation")
    benchmark_dir = root / "benchmarks" / "feynman_clifford"
    if suite == "small":
        names = SEARCH_QASM if split == "search" else VALIDATION_QASM
        paths = [benchmark_dir / name for name in names]
    elif suite == "feynman_all":
        paths = sorted(benchmark_dir.glob("*.qasm"))
    elif suite == "qasm":
        configured = os.environ.get("FT_ZX_QASM_PATH")
        if not configured:
            raise ValueError("FT_ZX_SUITE=qasm requires FT_ZX_QASM_PATH")
        source = Path(configured).expanduser().resolve()
        paths = sorted(source.glob("*.qasm")) if source.is_dir() else [source]
    else:
        raise ValueError("FT_ZX_SUITE must be small, feynman_all, or qasm")
    if not paths:
        raise ValueError("No QASM inputs found; empty evaluation suites are invalid")
    cases = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Missing benchmark: {path}")
        # These are already converted static Clifford traces. Do not inject T
        # states again or resample the conversion's measurement decisions.
        cases.append((f"qasm:{path.name}", preprocess(qasm2.load(str(path)))))
    if suite == "small":
        first_seed = 101 if split == "search" else 10001
        for qubits, layers in RANDOM_SIZES:
            for seed in range(first_seed, first_seed + 3):
                circuit = random_layered_clifford_circuit(qubits, layers, seed)
                name = f"random:q{qubits}:layers{layers}:seed{seed}"
                cases.append((name, preprocess(circuit)))
    return cases


def _encode_circuit(circuit) -> dict:
    return {
        "num_qubits": circuit.num_qubits,
        "gates": [
            {"id": gate.id, "kind": gate.kind, "qubits": gate.qubits,
             "is_executable": gate.is_executable, "reset_epochs": gate.reset_epochs}
            for node in circuit.g1 for gate in (circuit.gate(node),)
        ],
        "g1_edges": list(circuit.g1.edges),
        "g2_nodes": list(circuit.g2.nodes),
        "g2_edges": list(circuit.g2.edges),
    }


def _decode_circuit(data: dict):
    import networkx as nx
    from ftqc_patch_rotation.ir.rotation import GateNode, PreparedCircuit

    g1, g2 = nx.DiGraph(), nx.DiGraph()
    for record in data["gates"]:
        gate = GateNode(record["id"], record["kind"], tuple(record["qubits"]),
                        record["is_executable"], tuple(record["reset_epochs"]))
        g1.add_node(gate.id, gate=gate)
    g1.add_edges_from(data["g1_edges"])
    for node in data["g2_nodes"]:
        g2.add_node(node, **g1.nodes[node])
    g2.add_edges_from(data["g2_edges"])
    return PreparedCircuit(data["num_qubits"], g1, g2)


def _limit_worker_memory() -> None:
    """Hard memory cap; Windows Job Objects also contain child processes."""
    if MEMORY_LIMIT_MB <= 0:
        raise ValueError("FT_ZX_MEMORY_LIMIT_MB must be positive")
    limit = MEMORY_LIMIT_MB * 1024 * 1024
    if os.name != "nt":
        import resource
        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        limit = min(limit, hard) if hard != resource.RLIM_INFINITY else limit
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        return

    import ctypes as ct
    from ctypes import wintypes as wt

    class BasicLimit(ct.Structure):
        _fields_ = [("process_time", ct.c_longlong), ("job_time", ct.c_longlong),
                    ("flags", wt.DWORD), ("min_working_set", ct.c_size_t),
                    ("max_working_set", ct.c_size_t), ("active", wt.DWORD),
                    ("affinity", ct.c_size_t), ("priority", wt.DWORD),
                    ("scheduling", wt.DWORD)]

    class IOCounters(ct.Structure):
        _fields_ = [(name, ct.c_ulonglong) for name in
                    ("read_ops", "write_ops", "other_ops", "read", "write", "other")]

    class ExtendedLimit(ct.Structure):
        _fields_ = [("basic", BasicLimit), ("io", IOCounters),
                    ("process_memory", ct.c_size_t), ("job_memory", ct.c_size_t),
                    ("peak_process_memory", ct.c_size_t), ("peak_job_memory", ct.c_size_t)]

    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ct.c_void_p, wt.LPCWSTR]
    kernel.CreateJobObjectW.restype = wt.HANDLE
    kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD]
    kernel.SetInformationJobObject.restype = wt.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    kernel.AssignProcessToJobObject.restype = wt.BOOL
    kernel.GetCurrentProcess.restype = wt.HANDLE
    global _WINDOWS_JOB
    _WINDOWS_JOB = kernel.CreateJobObjectW(None, None)
    if not _WINDOWS_JOB:
        raise ct.WinError(ct.get_last_error())
    info = ExtendedLimit()
    info.basic.flags = 0x100 | 0x200 | 0x2000  # process/job memory + kill on close
    info.process_memory = info.job_memory = limit
    if not kernel.SetInformationJobObject(_WINDOWS_JOB, 9, ct.byref(info), ct.sizeof(info)):
        raise ct.WinError(ct.get_last_error())
    if not kernel.AssignProcessToJobObject(_WINDOWS_JOB, kernel.GetCurrentProcess()):
        raise ct.WinError(ct.get_last_error())


def _worker(program: str, inputs: str, output: str) -> None:
    try:
        _limit_worker_memory()
        _configure_compiler()
        import numpy as np

        data = json.loads(Path(inputs).read_text(encoding="utf-8"))
        random.seed(0)
        np.random.seed(0)
        spec = importlib.util.spec_from_file_location("ft_zx_candidate", program)
        if spec is None or spec.loader is None:
            raise ImportError("Cannot load candidate module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        if not callable(getattr(module, "run_code", None)):
            raise ValueError("Candidate must define run_code(prepared_circuit)")
        solutions = []
        for index, encoded in enumerate(data):
            random.seed(0)
            np.random.seed(0)
            circuit = _decode_circuit(encoded)
            # A one-flip-per-blocked-CZ construction is always possible. The
            # generous cap only prevents unbounded iterators/output flooding.
            cap = 2 * len(circuit.g2) + circuit.num_qubits + 1
            sequence = list(itertools.islice(iter(module.run_code(circuit)), cap + 1))
            if len(sequence) > cap:
                raise ValueError(f"case {index}: rotation sequence exceeds {cap} entries")
            if any(isinstance(q, bool) or not isinstance(q, numbers.Integral) for q in sequence):
                raise TypeError(f"case {index}: rotation IDs must be integers, not bool/float")
            solutions.append([int(q) for q in sequence])
        result = {"solutions": solutions}
    except BaseException as exc:
        result = {"error": f"{type(exc).__name__}: {exc}"[:1600]}
    Path(output).write_text(json.dumps(result, allow_nan=False), encoding="utf-8")


def run_with_timeout(program_path: Path, circuits: list[dict], timeout_seconds: float):
    with tempfile.TemporaryDirectory(prefix="ft_zx_") as temporary:
        folder = Path(temporary)
        inputs, output = folder / "inputs.json", folder / "solutions.json"
        inputs.write_text(json.dumps(circuits), encoding="utf-8")
        env = os.environ.copy()
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                     "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS"):
            env[name] = "1"
        env["PYTHONHASHSEED"] = "0"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        # Candidate files are reconstructed by SimpleTES in temporary directories;
        # never resolve the compiler or evaluator relative to those files.
        command = [sys.executable, str(Path(__file__).resolve()), "--worker",
                   str(program_path), str(inputs), str(output)]
        process = subprocess.Popen(command, cwd=folder, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=(os.name != "nt"))
        try:
            process.wait(timeout=timeout_seconds)
        except BaseException:
            if os.name == "nt":
                process.kill()  # closing the worker's Job handle kills descendants
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
            raise
        if not output.is_file():
            raise RuntimeError(f"Candidate worker exited {process.returncode} without a result")
        if output.stat().st_size > MAX_RESULT_BYTES:
            raise ValueError("Candidate result exceeds the JSON size limit")
        result = json.loads(output.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise TypeError("Candidate worker result must be a JSON object")
        if "error" in result:
            raise RuntimeError(result["error"])
        if process.returncode != 0:
            raise RuntimeError(f"Candidate worker exited {process.returncode}")
        return result["solutions"]


def validate_solution(circuit, sequence) -> int:
    """Replay an untrusted sequence against the untouched trusted input."""
    from ftqc_patch_rotation.passes.patch_rotation.simulator import simulate_rotations
    from ftqc_patch_rotation.passes.patch_rotation.schedule import build_schedule

    if not isinstance(sequence, list):
        raise TypeError("Each solution must be a list of qubit IDs")
    if any(type(q) is not int or not 0 <= q < circuit.num_qubits for q in sequence):
        raise ValueError("Rotation IDs must be integers within the circuit's qubit range")
    replay = simulate_rotations(circuit, sequence)
    if not replay.complete or len(replay.executed) != len(circuit.g2):
        raise ValueError("Rotation sequence leaves CZ gates unexecuted")
    # G2 checks orientation feasibility; G1 additionally checks resets and the
    # dependency barriers of retained non-CZ gates. Both must complete.
    schedule = build_schedule(circuit, sequence)
    if sum(op.source_node is not None for op in schedule) != len(circuit.g1):
        raise ValueError("Rotation sequence does not execute the complete logical circuit")
    # Count every submitted ROT, including useless/trailing flips, rather than
    # relying on simulate_rotations(), which truncates its used-rotation list.
    return len(sequence)


def compute_score(total_rotations: int, greedy_total_rotations: int) -> float:
    return (1.0 + greedy_total_rotations) / (1.0 + total_rotations)


def evaluate(filepath: str) -> dict:
    started = time.monotonic()
    rows = []
    try:
        if (not math.isfinite(TIMEOUT_SECONDS) or TIMEOUT_SECONDS <= 0
                or not math.isfinite(SOLVER_TIMEOUT_SECONDS) or SOLVER_TIMEOUT_SECONDS <= 0):
            raise ValueError("Evaluation and solver timeouts must be finite and positive")
        program = Path(filepath).expanduser().resolve(strict=True)
        root = _configure_compiler()
        from ftqc_patch_rotation.passes.patch_rotation.greedy import greedy_optimize

        cases = _build_cases(root)
        baseline = []
        for name, circuit in cases:
            sequence = list(greedy_optimize(circuit))
            try:
                baseline.append(validate_solution(circuit, sequence))
            except Exception as exc:
                raise ValueError(f"Greedy baseline is invalid on {name}: {exc}") from exc
        remaining = TIMEOUT_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("Evaluation budget exhausted while preparing inputs")
        solutions = run_with_timeout(program, [_encode_circuit(c) for _, c in cases],
                                     min(SOLVER_TIMEOUT_SECONDS, remaining))
        if not isinstance(solutions, list) or len(solutions) != len(cases):
            raise ValueError("Candidate must return one rotation sequence for every case")
        for (name, circuit), sequence, greedy_count in zip(cases, solutions, baseline):
            try:
                count = validate_solution(circuit, sequence)
            except Exception as exc:
                raise ValueError(f"{name}: {exc}") from exc
            rows.append({"case": name, "num_qubits": circuit.num_qubits,
                         "cz_gates": len(circuit.g2), "rotations": count,
                         "greedy_rotations": greedy_count})
        if time.monotonic() - started > TIMEOUT_SECONDS:
            raise TimeoutError("Total evaluation timeout exceeded during validation")
        total = sum(row["rotations"] for row in rows)
        greedy_total = sum(baseline)
        return {"combined_score": compute_score(total, greedy_total), "validity": 1.0,
                "total_rotations": total, "mean_rotations": total / len(cases),
                "greedy_total_rotations": greedy_total,
                "saved_rotations": greedy_total - total, "num_cases": len(cases),
                "suite": os.environ.get("FT_ZX_SUITE", "small"),
                "split": os.environ.get("FT_ZX_SPLIT", "search"),
                "eval_time": time.monotonic() - started, "per_case": rows}
    except Exception as exc:
        return {"combined_score": 0.0, "validity": 0.0,
                "error": f"{type(exc).__name__}: {exc}"[:2000],
                "eval_time": time.monotonic() - started, "per_case": rows}


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        _worker(*sys.argv[2:])
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("program", help="Candidate Python program to evaluate")
        arguments = parser.parse_args()
        metrics = evaluate(arguments.program)
        print(json.dumps(metrics, indent=2, ensure_ascii=False, allow_nan=False))
        raise SystemExit(0 if metrics["validity"] == 1.0 else 1)
