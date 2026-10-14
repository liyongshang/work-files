"""Small, dependency-light views of NAQsim's actual pass inputs and outputs.

These functions inspect existing objects and never run a compiler pass or mutate
its data. All drawing functions return a matplotlib Figure, without calling
``show``. Labels are ASCII so the demo does not require a CJK font or LaTeX.
Layer numbers are zero based. Scheduler timestamps are in microseconds.
"""

from __future__ import annotations

from collections import defaultdict
from math import ceil

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyArrowPatch, Patch, Rectangle
import pandas as pd
import rustworkx as rx


_BLUE = "#2864a0"
_INK = "#26364a"
_CELL_COLORS = {"M": "#ffdfbd", "Y": "#e6d9f8", "N": "#dcecf6", ".": "#eeeeee"}
_INTERVAL_COLORS = {
    "QOP": "#4477aa", "PICK": "#dca64b", "SHUTTLE": "#dd7766",
    "DROP": "#55a080", "DELAY": "#b5b5b5",
}


def _name(value):
    """Accept either upstream Enum members or string endpoint node types."""
    if value is None:
        return ""
    return str(getattr(value, "name", value))


def _names(value):
    return tuple(str(item) for item in (value or ()))


def _join(value):
    return ", ".join(str(item) for item in value)


def _trace(value):
    return [value] if isinstance(value, dict) else list(value)


def _title(ax, title):
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=_INK, pad=14)


def circuit_table(circuit):
    """List operations in the input Qiskit circuit in program order."""
    rows = []
    for index, item in enumerate(circuit.data):
        rows.append({
            "op_index": index,
            "gate": item.operation.name,
            "qubits": tuple(circuit.find_bit(bit).index for bit in item.qubits),
            "clbits": tuple(circuit.find_bit(bit).index for bit in item.clbits),
            "params": tuple(str(param) for param in item.operation.params),
        })
    return pd.DataFrame(rows, columns=["op_index", "gate", "qubits", "clbits", "params"])


def draw_circuit(circuit, title="Pass input: Qiskit circuit"):
    """Draw the small demo circuit without pylatexenc or a Qiskit drawer.

    Each source operation gets a column. This shows program order, rather than
    claiming that the columns are the later NAQsim scheduling layers.
    """
    table = circuit_table(circuit)
    nq, nc = circuit.num_qubits, circuit.num_clbits
    nw = nq + nc
    fig, ax = plt.subplots(figsize=(max(8, 0.63 * len(table) + 2), max(3.2, 0.65 * nw + 1.4)))
    for index in range(nw):
        is_classical = index >= nq
        y = -index
        ax.plot([-0.45, len(table) - 0.35], [y, y], color="#a7b0bc", lw=1.1)
        if is_classical:
            ax.plot([-0.45, len(table) - 0.35], [y - 0.055, y - 0.055], color="#a7b0bc", lw=0.8)
        label = f"c[{index - nq}]" if is_classical else f"q[{index}]"
        ax.text(-0.65, y, label, ha="right", va="center", fontsize=10, color=_INK)
    for row in table.itertuples(index=False):
        x, gate, qubits = row.op_index, row.gate, row.qubits
        ys = [-q for q in qubits]
        if gate == "barrier":
            if ys:
                ax.plot([x, x], [min(ys) - 0.35, max(ys) + 0.35], ls="--", color="#999999")
            continue
        if gate in {"cx", "cnot"} and len(ys) == 2:
            ax.plot([x, x], ys, color=_BLUE, lw=1.6)
            ax.add_patch(Circle((x, ys[0]), 0.075, color=_BLUE, zorder=4))
            ax.add_patch(Circle((x, ys[1]), 0.20, facecolor="white", edgecolor=_BLUE, lw=1.6, zorder=4))
            ax.plot([x - 0.15, x + 0.15], [ys[1], ys[1]], color=_BLUE, zorder=5)
            ax.plot([x, x], [ys[1] - 0.15, ys[1] + 0.15], color=_BLUE, zorder=5)
        else:
            if len(ys) > 1:
                ax.plot([x, x], [min(ys), max(ys)], color=_BLUE, lw=1.4)
            for y in ys:
                label = {"reset": "|0>", "measure": "M"}.get(gate, gate.upper())
                ax.add_patch(Rectangle((x - 0.27, y - 0.25), 0.54, 0.5, facecolor="white", edgecolor=_BLUE, lw=1.4, zorder=4))
                ax.text(x, y, label, ha="center", va="center", fontsize=9, color=_INK, zorder=5)
        if gate == "measure" and qubits and row.clbits:
            cy = -(nq + row.clbits[0])
            ax.add_patch(FancyArrowPatch((x, -qubits[0] - 0.28), (x, cy + 0.08), arrowstyle="-|>", mutation_scale=9, color="#6b7380", lw=1.0))
        ax.text(x, 0.52, str(row.op_index), ha="center", fontsize=8, color="#777777")
    ax.set_xlim(-1.6, max(0.6, len(table) - 0.25))
    ax.set_ylim(-max(0, nw - 1) - 0.7, 1.05)
    ax.axis("off")
    _title(ax, title)
    fig.tight_layout()
    return fig


def dag_tables(dag):
    """Return node and edge DataFrames, including register endpoint nodes."""
    rows = []
    for index in dag.node_indices():
        node = dag[index]
        rows.append({
            "node_id": index,
            "node_type": _name(getattr(node, "inst_type", getattr(node, "uop_type", ""))),
            "name": str(getattr(node, "inst_name", getattr(node, "uop_name", ""))),
            "qregs": _names(getattr(node, "qreg_names", ())),
            "condition_cregs": _names(getattr(node, "creg_names_cond", ())),
            "output_creg": str(getattr(node, "creg_name_out", "")),
        })
    edges = [{"source": u, "target": v, "dependency": _name(data)}
             for u, v, data in dag.weighted_edge_list()]
    return (
        pd.DataFrame(rows, columns=["node_id", "node_type", "name", "qregs", "condition_cregs", "output_creg"]),
        pd.DataFrame(edges, columns=["source", "target", "dependency"]),
    )


def draw_dag(dag, title="Translated instruction DAG", show_edge_labels=True, direction="TB"):
    """Draw a deterministic topological layout of an instruction or uop DAG.

    The default top-to-bottom layout keeps the small demo's labels readable at
    ordinary notebook width. ``direction='LR'`` enables a horizontal view.
    """
    direction = direction.upper()
    if direction not in {"TB", "LR"}:
        raise ValueError("direction must be 'TB' or 'LR'")
    nodes, edges = dag_tables(dag)
    depth = {}
    for index in rx.topological_sort(dag):
        predecessors = list(dag.predecessor_indices(index))
        depth[index] = 1 + max((depth[p] for p in predecessors), default=-1)
    generations = defaultdict(list)
    for index in sorted(depth):
        generations[depth[index]].append(index)
    max_depth = max(generations, default=0)
    max_width = max((len(indices) for indices in generations.values()), default=1)
    size = ((12, max(4, 0.88 * (max_depth + 1) + 1.5)) if direction == "TB" else
            (max(8, min(36, 2.05 * (max_depth + 1))), max(4, 1.1 * max_width + 1.1)))
    fig, ax = plt.subplots(figsize=size)
    positions = {}
    for generation, indices in generations.items():
        for lane, index in enumerate(indices):
            centered_lane = lane - (len(indices) - 1) / 2
            positions[index] = ((2.0 * centered_lane, -generation) if direction == "TB" else
                                (2.0 * generation, -centered_lane))
    if direction == "TB":
        ax.set_xlim(-max_width - 0.75, max_width + 0.75)
        ax.set_ylim(-max_depth - 0.65, 0.65)
    else:
        ax.set_xlim(-1.1, 2 * max_depth + 1.1)
        ax.set_ylim(-max_width / 2 - 0.6, max_width / 2 + 0.6)
    for edge in edges.itertuples(index=False):
        start, end = positions[edge.source], positions[edge.target]
        # NAQsim register names C*/c* denote classical dependencies.
        classical = edge.dependency.upper().startswith("C")
        color = "#a86434" if classical else "#8c9aaa"
        # Curve dependencies that skip a generation past intermediate nodes.
        curvature = 0.12 if depth[edge.target] - depth[edge.source] > 1 else 0.0
        shrink = 24 if direction == "TB" else 38
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=9, shrinkA=shrink, shrinkB=shrink, lw=0.9,
                                    connectionstyle=f"arc3,rad={curvature}",
                                    linestyle="--" if classical else "-", color=color, zorder=1))
        if show_edge_labels and edge.dependency:
            # Arc3's midpoint is displaced perpendicular to the line in
            # display space; use that same midpoint for dependency labels.
            start_px, end_px = ax.transData.transform(start), ax.transData.transform(end)
            x_px = (start_px[0] + end_px[0]) / 2 + curvature * (end_px[1] - start_px[1]) / 2
            y_px = (start_px[1] + end_px[1]) / 2 - curvature * (end_px[0] - start_px[0]) / 2
            x, y = ax.transData.inverted().transform((x_px, y_px))
            ax.text(x + (0.07 if direction == "TB" else 0), y + (0 if direction == "TB" else 0.09),
                    edge.dependency, ha="left" if direction == "TB" else "center", va="center" if direction == "TB" else "bottom",
                    fontsize=7.5 if direction == "TB" else 6.5, color=color,
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 0.1}, zorder=2)
    for node in nodes.itertuples(index=False):
        x, y = positions[node.node_id]
        endpoint = node.node_type in {"qreg_in", "qreg_out", "creg_out"}
        color = "#f0eee7" if endpoint else "#e5eef9"
        name = node.name if endpoint else node.node_type
        regs = _join(node.qregs)
        label = f"{node.node_id}: {name}" + (f"\n{regs}" if regs else "")
        ax.text(x, y, label, ha="center", va="center", fontsize=9 if direction == "TB" else 7,
                bbox={"boxstyle": "round,pad=0.4", "facecolor": color, "edgecolor": "#8295aa", "linewidth": 0.8}, zorder=3)
    ax.axis("off")
    _title(ax, title)
    if len(edges):
        ax.legend(handles=[Line2D([0], [0], color="#8c9aaa", label="Quantum / ordering dependency"),
                           Line2D([0], [0], color="#a86434", ls="--", label="Classical dependency")],
                  loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=2, frameon=False, fontsize=8)
    fig.tight_layout()
    return fig


def instruction_table(inst_trace, req_trace=None):
    """One row for each instruction or request in each logical layer."""
    inst_trace = list(inst_trace)
    req_trace = [[] for _ in inst_trace] if req_trace is None else list(req_trace)
    if len(inst_trace) != len(req_trace):
        raise ValueError("Instruction and request traces must have equal lengths")
    rows = []
    for layer, (instructions, requests) in enumerate(zip(inst_trace, req_trace)):
        for kind, values in (("request", requests), ("instruction", instructions)):
            for index, inst in enumerate(values):
                rows.append({
                    "layer": layer, "kind": kind, "index_in_kind": index,
                    "inst_type": _name(getattr(inst, "inst_type", "")),
                    "qregs": _names(getattr(inst, "qreg_names", ())),
                    "condition_cregs": _names(getattr(inst, "creg_names_cond", ())),
                    "output_creg": str(getattr(inst, "creg_name_out", "")),
                    "cx_type": _name(getattr(inst, "cx_type", "")),
                })
    return pd.DataFrame(rows, columns=["layer", "kind", "index_in_kind", "inst_type", "qregs", "condition_cregs", "output_creg", "cx_type"])


def draw_instruction_layers(inst_trace, req_trace=None, title="Logical schedule: parallel items in each layer"):
    """Show each logical layer's resource requests and scheduled instructions."""
    inst_trace = list(inst_trace)
    table = instruction_table(inst_trace, req_trace)
    max_items = max((len(group) for _, group in table.groupby("layer")), default=1)
    fig, ax = plt.subplots(figsize=(max(9, min(25, 2.3 * max_items + 1.8)), max(3, 0.82 * len(inst_trace) + 1.6)))
    for layer in range(len(inst_trace)):
        items = table[table.layer == layer]
        ax.axhspan(-layer - 0.43, -layer + 0.43, color="#f7f9fc" if layer % 2 == 0 else "white", zorder=0)
        for column, item in enumerate(items.itertuples(index=False)):
            request = item.kind == "request"
            label = item.inst_type + "\n" + _join(item.qregs)
            if item.condition_cregs:
                label += "\nif " + _join(item.condition_cregs)
            if item.output_creg:
                label += " -> " + item.output_creg
            ax.text(2.4 * column, -layer, label, ha="center", va="center", fontsize=8,
                    bbox={"boxstyle": "round,pad=0.3", "facecolor": "#fff0dc" if request else "#e5eef9",
                          "edgecolor": "#c39651" if request else "#8da4bf", "linestyle": "--" if request else "-", "linewidth": 0.8})
    ax.set_xlim(-1.35, 2.4 * (max_items - 1) + 1.35)
    ax.set_ylim(-max(0, len(inst_trace) - 1) - 0.65, 0.65)
    ax.set_yticks([-i for i in range(len(inst_trace))], [f"Layer {i}" for i in range(len(inst_trace))])
    ax.set_xticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(axis="y", length=0)
    _title(ax, title)
    ax.legend(handles=[Patch(facecolor="#fff0dc", edgecolor="#c39651", ls="--", label="Resource request"),
                       Patch(facecolor="#e5eef9", edgecolor="#8da4bf", label="Instruction")],
              loc="upper right", bbox_to_anchor=(1, 1.09), ncol=2, frameon=False, fontsize=8)
    fig.tight_layout()
    return fig


def _plane_grid(plane):
    field = getattr(plane, "field", plane)
    grid, occupants = [], defaultdict(list)
    chars = {"PORT_M": "M", "PORT_Y": "Y", "NORMAL": "N", "INVALID": "."}
    for row_index, row in enumerate(field):
        grid_row = []
        for col_index, cell in enumerate(row):
            char = cell if isinstance(cell, str) else chars.get(_name(cell.type), ".")
            grid_row.append(char)
            occupants[(row_index, col_index)].extend(str(qn) for qn in getattr(cell, "occupants", ()))
        grid.append(grid_row)
    return grid, occupants


def _draw_plane_on_ax(ax, plane, mapping=None, qregs=None, title="Patch plane"):
    grid, occupants = _plane_grid(plane)
    # An explicit mapping overrides the snapshot occupants for comparisons.
    if mapping is not None:
        occupants = defaultdict(list)
        for name, pos in mapping.items():
            occupants[tuple(pos)].append(str(name))
    elif qregs is not None and not hasattr(plane, "field"):
        for name, reg in qregs.items():
            if _name(getattr(reg, "status", "")) != "INACTIVE":
                occupants[tuple(reg.pos)].append(str(name))
    h, w = len(grid), len(grid[0]) if grid else 0
    for r, row in enumerate(grid):
        for c, char in enumerate(row):
            ax.add_patch(Rectangle((c - 0.48, r - 0.48), 0.96, 0.96, facecolor=_CELL_COLORS.get(char, "#eeeeee"),
                                   edgecolor="#9babbb", lw=1.0, zorder=0))
            ax.text(c - 0.38, r - 0.3, char, ha="left", va="center", fontsize=9, color="#586c80")
            names = occupants[(r, c)]
            if names:
                ax.text(c, r + 0.06, "\n".join(names), ha="center", va="center", fontsize=10, color=_INK, fontweight="bold", zorder=3)
    ax.set_xlim(-0.6, max(0.6, w - 0.4))
    ax.set_ylim(max(0.6, h - 0.4), -0.6)
    ax.set_xticks(range(w))
    ax.set_yticks(range(h))
    ax.set_xlabel("Column")
    ax.set_ylabel("Row")
    ax.set_aspect("equal")
    for spine in ax.spines.values():
        spine.set_visible(False)
    _title(ax, title)
    return grid


def draw_plane(plane_char_or_plane, mapping=None, qregs=None, title="Patch plane"):
    """Draw M/Y ports, N cells, and every occupant of a snapshot cell."""
    grid, _ = _plane_grid(plane_char_or_plane)
    h, w = len(grid), len(grid[0]) if grid else 0
    fig, ax = plt.subplots(figsize=(max(4, 0.95 * w + 1.6), max(4, 0.95 * h + 1.6)))
    _draw_plane_on_ax(ax, plane_char_or_plane, mapping, qregs, title)
    ax.legend(handles=[Patch(facecolor=_CELL_COLORS[c], label=label) for c, label in
                       (("M", "M resource port"), ("Y", "Y resource port"), ("N", "Normal cell"))],
              loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3, frameon=False, fontsize=8)
    fig.tight_layout()
    return fig


def draw_mapping_comparison(plane_char, before, after, title="Qubit mapping: after initial perturbations and SA result"):
    """Compare the mapper's state after initial perturbations and SA result.

    Upstream ``random_mapping`` is copied after ``sa_init_perturb_num``
    unconditional initial moves (100 by default), immediately before the
    annealing ``while`` loop. It is not the earlier shuffled placement.
    """
    grid, _ = _plane_grid(plane_char)
    h, w = len(grid), len(grid[0]) if grid else 0
    fig, axes = plt.subplots(1, 2, figsize=(max(8, 2 * (0.9 * w + 1.5)), max(4, 0.9 * h + 1.9)))
    _draw_plane_on_ax(axes[0], plane_char, mapping=before, title="After initial perturbations; before SA loop")
    _draw_plane_on_ax(axes[1], plane_char, mapping=after, title="After: simulated annealing")
    fig.suptitle(title, x=0.05, ha="left", fontsize=13, fontweight="bold", color=_INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig


def _schedule_rows(trace):
    """Retain each resource interval; share uop IDs only by object identity."""
    schedules = _trace(trace)
    rows, summaries = [], []
    offset = 0.0
    for layer, schedule in enumerate(schedules):
        uop_ids, layer_rows = {}, []
        for resource, intervals in schedule.items():
            for interval_index, (uop, interval_type, interval) in enumerate(intervals):
                identity = id(uop)
                if identity not in uop_ids:
                    uop_ids[identity] = len(uop_ids)
                begin, end = map(float, interval)
                layer_rows.append({
                    "layer": layer, "resource": _name(resource), "interval_index": interval_index,
                    "uop_id": uop_ids[identity], "uop_type": _name(getattr(uop, "uop_type", "")),
                    "qregs": _names(getattr(uop, "qreg_names", ())), "interval_type": _name(interval_type),
                    "begin_us": begin, "end_us": end, "duration_us": end - begin,
                    "layer_offset_us": offset, "global_begin_us": offset + begin, "global_end_us": offset + end,
                })
        # Upstream starts the local clock at zero in every logical layer.
        duration = max((row["end_us"] for row in layer_rows), default=0.0)
        summaries.append({
            "layer": layer, "duration_us": duration, "global_begin_us": offset,
            "global_end_us": offset + duration, "interval_count": len(layer_rows),
            "unique_uop_count": len(uop_ids), "resource_count": sum(bool(values) for values in schedule.values()),
        })
        rows.extend(layer_rows)
        offset += duration
    return rows, summaries


def uop_intervals_table(trace):
    """Every interval on every resource, including repeated uop references."""
    rows, _ = _schedule_rows(trace)
    return pd.DataFrame(rows, columns=["layer", "resource", "interval_index", "uop_id", "uop_type", "qregs", "interval_type",
                                       "begin_us", "end_us", "duration_us", "layer_offset_us", "global_begin_us", "global_end_us"])


def layer_durations_table(trace):
    """Layer durations are max(local interval end), with cumulative offsets."""
    _, summaries = _schedule_rows(trace)
    return pd.DataFrame(summaries, columns=["layer", "duration_us", "global_begin_us", "global_end_us", "interval_count",
                                           "unique_uop_count", "resource_count"])


def draw_uop_gantt(trace, layer=None, title=None):
    """Plot exact resource intervals, using local or accumulated layer time."""
    schedules = _trace(trace)
    if layer is not None and not 0 <= layer < len(schedules):
        raise IndexError("Layer is outside the schedule trace")
    table = uop_intervals_table(schedules)
    summaries = layer_durations_table(schedules)
    if layer is not None:
        table = table[table.layer == layer]
    resources = list(dict.fromkeys(table.resource))
    fig, ax = plt.subplots(figsize=(14, max(3.4, 0.58 * len(resources) + 1.8)))
    start_column, end_column = (("begin_us", "end_us") if layer is not None else ("global_begin_us", "global_end_us"))
    ymax = max(1, len(resources))
    if layer is None:
        for row in summaries.itertuples(index=False):
            ax.axvspan(row.global_begin_us, row.global_end_us, color="#f3f5f8" if row.layer % 2 == 0 else "white", zorder=0)
            ax.axvline(row.global_begin_us, color="#c7ccd4", lw=0.7, zorder=1)
            ax.text((row.global_begin_us + row.global_end_us) / 2, ymax - 0.35, f"L{row.layer}", ha="center", fontsize=8, color="#717e8e")
    extent = float(table[end_column].max()) if len(table) else 1.0
    positions = {name: index for index, name in enumerate(resources)}
    for row in table.to_dict("records"):
        begin, end = row[start_column], row[end_column]
        color = _INTERVAL_COLORS.get(row["interval_type"], "#8e89bb")
        y = positions[row["resource"]]
        ax.broken_barh([(begin, end - begin)], (y - 0.29, 0.58), facecolors=color, edgecolors="white", linewidth=0.3, zorder=2)
        if end - begin > extent * 0.028:
            label = row["uop_type"] + (" " + _join(row["qregs"]) if row["qregs"] else "")
            ax.text((begin + end) / 2, y, label, ha="center", va="center", fontsize=6.5, color="white", clip_on=True, zorder=3)
    ax.set_yticks(range(len(resources)), resources)
    ax.set_ylim(-0.65, ymax - 0.1)
    ax.set_xlim(0, max(1.0, extent * 1.01))
    ax.set_xlabel("Local time within layer (us)" if layer is not None else "Cumulative time across layers (us)")
    ax.set_ylabel("Laser / AOD resource")
    ax.grid(axis="x", color="#e0e5eb", lw=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    _title(ax, title or (f"Micro-operation schedule: layer {layer}" if layer is not None else "Micro-operation schedule: all layers"))
    present = list(dict.fromkeys(table.interval_type))
    ax.legend(handles=[Patch(facecolor=_INTERVAL_COLORS.get(name, "#8e89bb"), label=name) for name in present],
              loc="upper center", bbox_to_anchor=(0.5, -0.20), ncol=max(1, len(present)), frameon=False, fontsize=8)
    fig.tight_layout()
    return fig


def draw_layer_durations(trace, title="Execution duration of each logical layer"):
    table = layer_durations_table(trace)
    fig, ax = plt.subplots(figsize=(max(7, 0.55 * len(table) + 2), 4))
    ax.bar(table.layer, table.duration_us, color=_BLUE, width=0.68)
    for row in table.itertuples(index=False):
        ax.annotate(f"{row.duration_us:.1f}", (row.layer, row.duration_us), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8)
    ax.set_xticks(table.layer)
    ax.set_xlabel("Logical layer")
    ax.set_ylabel("Duration (us)")
    ax.margins(y=0.2)
    ax.grid(axis="y", color="#e0e5eb", lw=0.6)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    _title(ax, title)
    fig.tight_layout()
    return fig


def _unique_uops(schedule):
    """A uop may appear on several resource rows; inspect it only once."""
    seen = set()
    for intervals in schedule.values():
        for uop, _, _ in intervals:
            if id(uop) not in seen:
                seen.add(id(uop))
                yield len(seen) - 1, uop


def _segment_qregs(uop, phase, src, dst):
    """Match regrouped first/second-stage segments to original move pairs."""
    first = [(tuple(s), tuple(d)) for _, s, d in getattr(uop, "first_move", ())]
    second = [(tuple(s), tuple(d)) for _, s, d in getattr(uop, "second_move", ())]
    names = []
    for qn, (original_src, original_dst) in zip(uop.qreg_names, uop.src_dst_list):
        original_src, original_dst = tuple(original_src), tuple(original_dst)
        direct = (src, dst) == (original_src, original_dst)
        if phase == "first_move":
            via = src == original_src and (dst, original_dst) in second
        else:
            via = dst == original_dst and (original_src, src) in first
        if direct or via:
            names.append(str(qn))
    return tuple(names)


def move_paths_table(trace, layer=None):
    """Scheduled MOVE segments from first_move/second_move, identity deduped.

    ``uop_begin_us``/``uop_end_us`` bound the entire MOVE on all its resources;
    they are not an individual segment's start/end or a sampled trajectory.
    """
    schedules = _trace(trace)
    if layer is not None and not 0 <= layer < len(schedules):
        raise IndexError("Layer is outside the schedule trace")
    rows = []
    for layer_index, schedule in enumerate(schedules):
        if layer is not None and layer_index != layer:
            continue
        for uop_id, uop in _unique_uops(schedule):
            if _name(getattr(uop, "uop_type", "")) != "MOVE":
                continue
            intervals = [interval for values in schedule.values() for other, _, interval in values if other is uop]
            begin = min((float(interval[0]) for interval in intervals), default=0.0)
            end = max((float(interval[1]) for interval in intervals), default=0.0)
            for phase in ("first_move", "second_move"):
                for segment, (direction, source, destination) in enumerate(getattr(uop, phase, ())):
                    src, dst = tuple(source), tuple(destination)
                    rows.append({
                        "layer": layer_index, "uop_id": uop_id, "phase": phase, "segment": segment,
                        "qregs": _segment_qregs(uop, phase, src, dst), "direction": _name(direction),
                        "src_row": src[0], "src_col": src[1], "dst_row": dst[0], "dst_col": dst[1],
                        "uop_begin_us": begin, "uop_end_us": end,
                    })
    return pd.DataFrame(rows, columns=["layer", "uop_id", "phase", "segment", "qregs", "direction", "src_row", "src_col",
                                       "dst_row", "dst_col", "uop_begin_us", "uop_end_us"])


def draw_move_paths(plane_char_or_plane, trace, layer, mapping=None, qregs=None, title=None):
    """Overlay actual two-stage MOVE routes on a supplied plane snapshot."""
    grid, _ = _plane_grid(plane_char_or_plane)
    h, w = len(grid), len(grid[0]) if grid else 0
    fig, ax = plt.subplots(figsize=(max(5, w * 1.15 + 2), max(5, h * 1.15 + 2)))
    _draw_plane_on_ax(ax, plane_char_or_plane, mapping, qregs, title or f"MOVE routes in layer {layer}; supplied layout")
    table = move_paths_table(trace, layer)
    colors = plt.get_cmap("tab10")
    uop_ids = list(dict.fromkeys(table.uop_id))
    for row in table.itertuples(index=False):
        color = colors(uop_ids.index(row.uop_id) % 10)
        start, end = (row.src_col, row.src_row), (row.dst_col, row.dst_row)
        if start != end:
            ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=15, shrinkA=10, shrinkB=10,
                                        lw=2, ls="-" if row.phase == "first_move" else "--", color=color, alpha=0.8, zorder=2))
        label = f"u{row.uop_id}: {_join(row.qregs)}"
        x, y = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
        ax.text(x + 0.07, y - 0.12, label, fontsize=7, color=color,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 1}, zorder=4)
    ax.legend(handles=[Line2D([0], [0], color=_BLUE, lw=2, label="first_move"),
                       Line2D([0], [0], color=_BLUE, lw=2, ls="--", label="second_move")],
              loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, frameon=False, fontsize=9)
    if table.empty:
        ax.text(0.5, -0.12, "No scheduled MOVE in this layer", transform=ax.transAxes, ha="center", fontsize=9)
    fig.tight_layout()
    return fig


def qregs_table(trace):
    """All recorded registers and statuses at each layer end."""
    rows = []
    for layer, registers in enumerate(_trace(trace)):
        for name, reg in registers.items():
            pos = tuple(reg.pos) if reg.pos is not None else (None, None)
            rows.append({"layer": layer, "qreg": str(name), "row": pos[0], "col": pos[1], "status": _name(reg.status)})
    return pd.DataFrame(rows, columns=["layer", "qreg", "row", "col", "status"])


def draw_qreg_snapshots(plane_trace, qregs_trace=None, layers=None, columns=3, title="Patch occupancy at the end of each logical layer"):
    """Show every selected layer-end snapshot; occupants come from its cells."""
    planes = list(plane_trace)
    layers = list(range(len(planes))) if layers is None else list(layers)
    if not layers:
        raise ValueError("At least one snapshot layer is required")
    if any(not 0 <= layer < len(planes) for layer in layers):
        raise IndexError("Layer is outside the plane trace")
    if qregs_trace is not None and len(qregs_trace) != len(planes):
        raise ValueError("Plane and register traces must have equal lengths")
    columns = min(max(1, int(columns)), len(layers))
    rows = ceil(len(layers) / columns)
    grid, _ = _plane_grid(planes[layers[0]])
    h, w = len(grid), len(grid[0]) if grid else 0
    fig, axes = plt.subplots(rows, columns, squeeze=False, figsize=(columns * max(3, 0.65 * w + 1.2), rows * max(3.3, 0.65 * h + 1.3)))
    for ax, layer in zip(axes.flat, layers):
        qregs = None if qregs_trace is None else qregs_trace[layer]
        _draw_plane_on_ax(ax, planes[layer], qregs=qregs, title=f"End of layer {layer}")
    for ax in list(axes.flat)[len(layers):]:
        ax.axis("off")
    fig.suptitle(title, x=0.04, ha="left", fontsize=13, fontweight="bold", color=_INK)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig
