from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Rectangle

from .schedule import ScheduledOperation
from .compiler import CompiledCircuit


def _gate_label(kind: str) -> str:
    return {
        "rot": "R", "reset": "|0>", "sdg": "S†",
        "folding": "Fold", "unfolding": "Unfold", "icz": "iCZ",
    }.get(kind, kind.upper())


def _gate_width(label: str) -> float:
    return 0.56 if len(label) == 1 else max(0.80, 0.22 * len(label) + 0.24)


def draw_schedule(
    schedule: tuple[ScheduledOperation, ...] | list[ScheduledOperation],
    num_qubits: int,
    output: str | Path,
    title: str = "Patch-rotation optimized Clifford circuit",
    qubit_labels: tuple[str, ...] | None = None,
) -> Path:
    """Draw a circuit with blue/red orientation wires and reset boundaries."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Allocate label-dependent space, including a clear gap between boxes.
    # Equal axis scaling makes single-letter boxes genuinely square on screen.
    centers = []
    cursor = 0.4
    for operation in schedule:
        gate_width = 0.32 if operation.kind == "cz" else _gate_width(_gate_label(operation.kind))
        centers.append(cursor + gate_width / 2)
        cursor += gate_width + 0.38
    end_x = cursor + 0.4
    width = min(120.0, max(8.0, 0.60 * (end_x + 1.0)))
    fig, ax = plt.subplots(figsize=(width, max(3.0, 0.65 * num_qubits + 1.5)))
    colors = [False] * num_qubits
    x_positions = [0.0] * num_qubits
    y_positions = [num_qubits - 1 - q for q in range(num_qubits)]

    if qubit_labels is not None and len(qubit_labels) != num_qubits:
        raise ValueError("qubit_labels length must equal num_qubits")
    labels = qubit_labels or tuple(f"q{q}" for q in range(num_qubits))
    for q, y in enumerate(y_positions):
        ax.text(-0.25, y, labels[q], ha="right", va="center")

    def wire(q: int, end_x: float) -> None:
        color = "#d62728" if colors[q] else "#1f77b4"
        ax.plot([x_positions[q], end_x], [y_positions[q], y_positions[q]], color=color, lw=2)
        x_positions[q] = end_x

    gate_texts = []
    for x, operation in zip(centers, schedule):
        if operation.kind == "cz":
            q0, q1 = operation.qubits
            wire(q0, x)
            wire(q1, x)
            y0, y1 = y_positions[q0], y_positions[q1]
            ax.plot([x, x], [y0, y1], color="#333333", lw=1.8)
            for y in (y0, y1):
                ax.add_patch(Circle((x, y), 0.16, facecolor="#7b2cbf", edgecolor="black", zorder=3))
        elif len(operation.qubits) == 1:
            q = operation.qubits[0]
            wire(q, x)
            y = y_positions[q]
            face = {
                "h": "#ffbf00",
                "rot": "#2ca02c",
                "reset": "#E6E6E6",
                "s": "#17becf",
                "icz": "#c5a3e6",
                "sdg": "#9edae5",
                "x": "#e377c2",
                "y": "#bcbd22",
                "z": "#8c564b",
                "folding": "#c7c7c7",
                "unfolding": "#c7c7c7",
            }.get(operation.kind, "#dddddd")
            label = _gate_label(operation.kind)
            box_width = _gate_width(label)
            ax.add_patch(Rectangle((x - box_width / 2, y - 0.28), box_width, 0.56, facecolor=face, edgecolor="black", zorder=3))
            gate_texts.append(ax.text(x, y, label, ha="center", va="center", fontsize=12, zorder=4))
            if operation.kind == "reset":
                colors[q] = False
            elif operation.kind in {"h", "rot"}:
                colors[q] = not colors[q]
        elif len(operation.qubits) == 2:
            q0, q1 = operation.qubits
            wire(q0, x)
            wire(q1, x)
            y0, y1 = y_positions[q0], y_positions[q1]
            ax.plot([x, x], [y0, y1], color="#555555", lw=1.5)
            ax.text(x, (y0 + y1) / 2, operation.kind.upper(), fontsize=6,
                    ha="center", va="center",
                    bbox={"boxstyle": "round,pad=0.15", "fc": "#dddddd", "ec": "#555555"})
        else:
            raise ValueError(f"unsupported scheduled operation: {operation.kind}")

    for q in range(num_qubits):
        wire(q, end_x)
    ax.set_xlim(-0.7, end_x + 0.3)
    ax.set_ylim(-0.7, num_qubits - 0.3)
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title, pad=34)
    ax.axis("off")
    ax.legend(
        handles=[
            Line2D([0], [0], color="#1f77b4", lw=2, label="orientation 0"),
            Line2D([0], [0], color="#d62728", lw=2, label="orientation 1"),
        ],
        loc="lower right",
        bbox_to_anchor=(1.0, 1.01),
        ncol=2,
        frameon=False,
    )
    fig.tight_layout()
    fig.canvas.draw()
    # Very deep circuits still fit the raster-size cap without text escaping
    # the boxes. Ordinary circuits use the full 12-point labels.
    points_per_unit = ax.get_window_extent().height / num_qubits * 72 / fig.dpi
    for text in gate_texts:
        text.set_fontsize(min(12.0, points_per_unit * 0.28))
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return output


def draw_compiled_circuit(
    circuit: CompiledCircuit,
    output: str | Path,
    title: str = "Compiled Clifford circuit",
    qubit_labels: tuple[str, ...] | None = None,
) -> Path:
    """Visualize a compiled DAG in a deterministic topological order."""
    schedule = [
        ScheduledOperation(op.kind, op.qubits, op.source_node)
        for op in circuit.operations()
    ]
    return draw_schedule(schedule, circuit.num_qubits, output, title, qubit_labels)
