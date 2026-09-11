"""Convert Feynman's OpenQASM benchmarks to magic-state-injected Clifford traces."""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path


GATE_RE = re.compile(r"^(ccx|t|tdg)\s+(.+);\s*$", re.IGNORECASE)


def _ccz_injection(qubits: list[str], bits: tuple[int, int, int]) -> list[str]:
    a, b, c = qubits
    m0, m1, m2 = bits
    lines = [
        f"// CCZ injection; sampled CCZReg measurement = {m0}{m1}{m2}",
        f"cx {a},cczreg[0];",
        f"cx {b},cczreg[1];",
        f"cx {c},cczreg[2];",
        "measure cczreg -> cczmeas;",
    ]
    # Ratio between the measured branch and CCZ is a Clifford correction.
    # Use parity sets so degenerate Feynman operands are still legal QASM:
    # CZ(q,q)=Z(q), and duplicate corrections cancel modulo two.
    cz_terms: set[tuple[str, str]] = set()
    z_terms: set[str] = set()

    def toggle_cz(left: str, right: str) -> None:
        if left == right:
            if left in z_terms:
                z_terms.remove(left)
            else:
                z_terms.add(left)
            return
        term = tuple(sorted((left, right)))
        if term in cz_terms:
            cz_terms.remove(term)
        else:
            cz_terms.add(term)

    def toggle_z(qubit: str) -> None:
        if qubit in z_terms:
            z_terms.remove(qubit)
        else:
            z_terms.add(qubit)

    if m0:
        toggle_cz(b, c)
    if m1:
        toggle_cz(a, c)
    if m2:
        toggle_cz(a, b)
    if m0 and m1:
        toggle_z(c)
    if m0 and m2:
        toggle_z(b)
    if m1 and m2:
        toggle_z(a)
    lines.extend(f"cz {left},{right};" for left, right in sorted(cz_terms))
    lines.extend(f"z {qubit};" for qubit in sorted(z_terms))
    lines.extend("reset cczreg[{}];".format(index) for index in range(3))
    return lines


def _t_injection(qubit: str, bit: int, dagger: bool) -> list[str]:
    name = "Tdg" if dagger else "T"
    lines = [
        f"// {name} injection; sampled TReg measurement = {bit}",
        f"cx {qubit},treg[0];",
        "measure treg[0] -> tmeas[0];",
    ]
    if bit:
        lines.append(f"s {qubit};")
    if dagger:
        # Tdg = Sdg T, so the same |T> resource suffices.
        lines.append(f"sdg {qubit};")
    lines.append("reset treg[0];")
    return lines


def convert_text(text: str, rng: random.Random) -> tuple[str, dict[str, int]]:
    output: list[str] = []
    declarations_inserted = False
    stats = {"ccx": 0, "t": 0, "tdg": 0}

    for original in text.splitlines():
        stripped = original.strip()
        if stripped.lower().startswith("qreg ") and not declarations_inserted:
            output.extend(
                [
                    original,
                    # OpenQASM 2 identifiers must begin with lowercase. These
                    # are the requested logical CCZReg and TReg registers.
                    "qreg cczreg[3]; // CCZReg[3]",
                    "qreg treg[1]; // TReg[1]",
                    "creg cczmeas[3];",
                    "creg tmeas[1];",
                ]
            )
            declarations_inserted = True
            continue

        match = GATE_RE.match(stripped)
        if not match:
            output.append(original)
            continue

        gate = match.group(1).lower()
        operands = [item.strip() for item in match.group(2).split(",")]
        stats[gate] += 1
        if gate == "ccx":
            if len(operands) != 3:
                raise ValueError(f"invalid ccx: {original}")
            output.append(f"h {operands[2]};")
            bits = tuple(rng.randrange(2) for _ in range(3))
            output.extend(_ccz_injection(operands, bits))
            output.append(f"h {operands[2]};")
        else:
            if len(operands) != 1:
                raise ValueError(f"invalid {gate}: {original}")
            output.extend(_t_injection(operands[0], rng.randrange(2), gate == "tdg"))

    if not declarations_inserted:
        raise ValueError("input has no qreg declaration")
    return "\n".join(output) + "\n", stats
