"""Draw source-faithful d=3 SE diagrams using Qiskit and Matplotlib.

The Qiskit objects are drawing-only: basis readout/reset, software frame updates,
and atom-role changes use explicit labelled glyphs. Original Stim is exported
separately. No generated drawing circuit is passed to the logical compiler.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import html
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit import Instruction


TITLES = {"swap": "SWAP SE", "mid_swap": "Mid-SWAP SE",
          "teleportation": "Teleportation SE", "modified_steane": "Modified Steane SE"}
COLORS = {"data": "#1769aa", "ancilla": "#c66b13", "fresh_layer": "#7b4ab2",
          "prep_data": "#7b4ab2", "encoded_ancilla": "#7b4ab2", "free": "#8a939e"}
ROLE_LABEL = {"data": "D", "ancilla": "A", "fresh_layer": "F",
              "prep_data": "P", "encoded_ancilla": "EA", "free": "free"}
STAGES = {
    "round_reset": "Ancilla reset", "data_entry": "Fresh data entry",
    "interaction_1": "Interaction 1", "interaction_2": "Interaction 2",
    "interaction_3": "Interaction 3", "interaction_4": "Interaction 4",
    "round_end_shuttle": "End-round shuttle", "mid_round_shuttle": "Mid-round shuttle",
    "round_SSR": "SSR + frame", "encoded_preparation_reset": "Fresh block reset",
    "encoded_preparation_0": "Prep checks 1/3", "encoded_preparation_1": "Prep checks 2/3",
    "encoded_preparation_2": "Prep checks 3/3", "preparation_frame": "Prep frame",
    "encoded_block_ready": "Encoded ancilla ready", "transversal_fresh_to_old": "Fresh-to-old CX",
    "transversal_old_to_fresh": "Old-to-fresh CX", "old_block_SSR": "Old block SSR",
    "logical_transfer_frame": "Transfer frame", "logical_transfer": "Data transfer",
    "xzzx_input_frame": "Enter XZZX frame", "xzzx_output_frame": "Restore CSS frame",
}


def stage_name(stage):
    return STAGES.get(stage, stage.replace("_", " "))


def extract_moments(program):
    """Keep physical TICK boundaries and explicit record indices in source order."""
    moments, annotations, current, operations = [], [], {}, []
    before = {}
    stages = []
    mcount = 0
    counts = Counter()

    def start(stage):
        nonlocal before
        if not operations:
            before = deepcopy(current)
        if stage and stage not in stages:
            stages.append(stage)

    def flush():
        nonlocal before
        if operations:
            moments.append({"before": before, "after": deepcopy(current),
                            "stages": list(stages), "operations": list(operations)})
        operations.clear()
        stages.clear()

    for op in program.circuit.flattened():
        info = program.steps.get(op.tag, {})
        stage = info.get("stage", "")
        targets = op.targets_copy()
        if op.name == "QUBIT_COORDS":
            continue
        if op.tag.startswith("ideal:"):
            for q, state in info.get("states", {}).items():
                current[q] = {**state, "active": True}
            continue
        if op.name in {"DETECTOR", "OBSERVABLE_INCLUDE", "SHIFT_COORDS"}:
            annotations.append({"name": op.name, "tag": op.tag,
                                "records": [mcount + t.value for t in targets if t.is_measurement_record_target],
                                "args": op.gate_args_copy()})
            continue
        if op.name == "TICK":
            flush()
            if info.get("states"):
                start(stage)
                for q, state in info["states"].items():
                    current[q] = {**state, "active": current.get(q, {}).get("active", True)}
                    role = ROLE_LABEL[state["role"]]
                    label = f"{role}@s{state['site'][1]}" if op.tag.startswith("move:") else f"to {role}"
                    operations.append({"kind": "role", "wires": [q], "label": label,
                                       "tag": op.tag, "stage": stage, "state": state})
                flush()
            continue
        start(stage)
        for q, state in info.get("states", {}).items():
            current[q] = {**state, "active": current.get(q, {}).get("active", False)}
        if op.name in {"CX", "CZ"}:
            for a, b in zip(targets[::2], targets[1::2]):
                if a.is_measurement_record_target and b.is_qubit_target:
                    record = mcount + a.value
                    assert 0 <= record < mcount
                    pauli = "X" if op.name == "CX" else "Z"
                    operations.append({"kind": "frame", "wires": [b.value],
                                       "label": f"{pauli}[m{record}]", "record": record,
                                       "tag": op.tag, "stage": stage})
                    counts["feedback"] += 1
                elif a.is_qubit_target and b.is_qubit_target:
                    operations.append({"kind": op.name.lower(), "wires": [a.value, b.value],
                                       "tag": op.tag, "stage": stage})
                    counts[op.name] += 1
                else:
                    raise ValueError(f"unsupported controlled instruction: {op}")
        elif op.name in {"R", "RX", "M", "MX"}:
            basis = "X" if op.name.endswith("X") else "Z"
            for target in targets:
                q = target.value
                if op.name.startswith("R"):
                    current[q]["active"] = True
                    role = ROLE_LABEL[current[q]["role"]]
                    label, kind = f"R{basis} {role}", "reset"
                    record = None
                    counts["reset"] += 1
                else:
                    label, kind = f"M{basis}:m{mcount}", "measure"
                    record = mcount
                    mcount += 1
                    current[q]["active"] = False
                    counts["measurement"] += 1
                operations.append({"kind": kind, "wires": [q], "label": label,
                                   "record": record, "tag": op.tag, "stage": stage})
        elif op.name in {"H", "X", "Y", "Z", "S", "S_DAG"}:
            for target in targets:
                operations.append({"kind": op.name.lower(), "wires": [target.value],
                                   "tag": op.tag, "stage": stage})
                counts[op.name] += 1
        else:
            raise ValueError(f"unhandled Stim instruction {op}")
    flush()
    assert mcount == program.circuit.num_measurements == len(program.measurements)
    shown_records = [(x["record"], x["wires"][0]) for m in moments for x in m["operations"] if x["kind"] == "measure"]
    assert shown_records == [(x["index"], x["wire"]) for x in program.measurements]
    assert all(current[q]["role"] == "data" and current[q]["active"] for q in program.final_data)
    # Check that no non-ideal quantum entangler disappeared during diagram extraction.
    expected = Counter()
    for op in program.circuit.flattened():
        if op.tag.startswith("ideal:") or op.name not in {"CX", "CZ"}:
            continue
        ts = op.targets_copy()
        for a, b in zip(ts[::2], ts[1::2]):
            if a.is_qubit_target and b.is_qubit_target:
                expected[(op.name.lower(), a.value, b.value, op.tag)] += 1
    actual = Counter((x["kind"], *x["wires"], x["tag"]) for m in moments for x in m["operations"] if x["kind"] in {"cx", "cz"})
    assert actual == expected
    return moments, annotations, counts


def make_circuit(moments, wires):
    registers = {q: QuantumRegister(1, f"w{q:02d}") for q in wires}
    circuit = QuantumCircuit(*registers.values())
    for i, moment in enumerate(moments):
        for op in moment["operations"]:
            qs = [registers[q][0] for q in op["wires"]]
            kind = op["kind"]
            if kind in {"cx", "cz", "h", "x", "y", "z", "s"}:
                getattr(circuit, kind)(*qs)
            elif kind == "s_dag":
                circuit.sdg(qs[0])
            else:
                circuit.append(Instruction(kind, 1, 0, [], label=op["label"]), qs)
        if i < len(moments) - 1:
            circuit.barrier()
    return circuit


def render_page(program, moments, wires, page, pages, output, start_index):
    circuit = make_circuit(moments, wires)
    style = {
        "backgroundcolor": "#ffffff", "textcolor": "#203248", "linecolor": "#68788c",
        "fontsize": 11, "subfontsize": 8, "displaycolor": {
            "h": ("#e1edff", "#174e85"), "cx": ("#2b65a0", "#ffffff"),
            "cz": ("#2b65a0", "#ffffff"), "reset": ("#eaf3fb", "#174e85"),
            "measure": ("#fff0d9", "#9a510a"), "frame": ("#eee5fc", "#7041a3"),
            "role": ("#dff1e9", "#126444"),
        },
    }
    fig = circuit.draw(output="mpl", fold=-1, idle_wires=True, style=style,
                       plot_barriers=True, scale=0.85)
    ax = fig.axes[0]
    state = moments[0]["before"]
    exit_labels = []
    for text in list(ax.texts):
        value = text.get_text()
        if not value.startswith("${w"):
            continue
        for q in wires:
            if f"w{q:02d}" in value:
                s = state.get(q, {})
                role = s.get("role", "free") if s.get("active", False) else "free"
                slot = "D" if q % 17 in program.initial_data else "A"
                role_label = ROLE_LABEL.get(role, role) if role != "free" else f"{slot}-slot/free"
                text.set_text(f"w{q:02d} | {role_label}")
                text.set_color(COLORS.get(role, COLORS["free"]))
                text.set_fontweight("bold")
                text.set_clip_on(False)
                after = moments[-1]["after"].get(q, {})
                out_role = after.get("role", "free") if after.get("active", False) else "free"
                exit_labels.append((text.get_position()[1], ROLE_LABEL.get(out_role, out_role),
                                    COLORS.get(out_role, COLORS["free"])))
                break
    assert len(exit_labels) == len(wires), "every physical wire needs a role label"
    for y, label, color in exit_labels:
        ax.text(ax.get_xlim()[1], y, f"  {label}", ha="left", va="center", fontsize=10,
                color=color, fontweight="bold", clip_on=False)
    # Attach notes to the axes, avoiding rescaling Qiskit's equal-aspect layout.
    w, h = fig.get_size_inches()
    title = f"{TITLES[program.scheme]}  |  d=3, one full round  |  {page}/{pages}"
    stage_list = []
    for moment in moments:
        for stage in moment["stages"]:
            name = stage_name(stage)
            if not stage_list or name != stage_list[-1]:
                stage_list.append(name)
    import textwrap
    subtitle = " / ".join(stage_list)
    ax.annotate(title, xy=(0, 1), xycoords="axes fraction", xytext=(0, 48),
                textcoords="offset points", fontsize=17, weight="bold", color="#19344f", va="bottom")
    ax.annotate(textwrap.fill(subtitle, width=max(80, int(w*8))), xy=(0, 1),
                xycoords="axes fraction", xytext=(0, 10), textcoords="offset points",
                fontsize=9, color="#53657b", va="bottom")
    ax.annotate(
             "Left / right labels: page entry / exit.   D: data   A: ancillary   P/EA: prep/encoded ancilla   F: fresh layer   free: unoccupied\n"
             "MZ/MX:m# = readout record; X/Z[m#] = software frame; green = role/site change, not a SWAP gate.",
             xy=(0, 0), xycoords="axes fraction", xytext=(0, -20), textcoords="offset points",
             fontsize=8, color="#53657b", va="top")
    target = output / f"page_{page:02d}"
    fig.savefig(target.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    fig.savefig(target.with_suffix(".png"), dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {"page": page, "start_moment": start_index, "moments": len(moments),
            "stages": stage_list, "svg": target.with_suffix(".svg").name,
            "png": target.with_suffix(".png").name}


def combine_svg(paths, output):
    """Stack complete vector pages into one zoomable SVG without rasterization."""
    ns = "http://www.w3.org/2000/svg"
    roots = [ET.parse(path).getroot() for path in paths]
    boxes = [list(map(float, root.attrib["viewBox"].split())) for root in roots]
    width = max(b[2] for b in boxes)
    height = sum(b[3] + 12 for b in boxes)
    combined = ET.Element(f"{{{ns}}}svg", {"viewBox": f"0 0 {width} {height}",
                         "width": f"{width}pt", "height": f"{height}pt"})
    offset = 0
    for index, (root, box) in enumerate(zip(roots, boxes)):
        # Matplotlib reuses SVG ids between figures; namespace every page.
        ids = {e.attrib["id"]: f"p{index}_{e.attrib['id']}" for e in root.iter() if "id" in e.attrib}
        for element in root.iter():
            for key, value in list(element.attrib.items()):
                if key == "id":
                    element.set(key, ids[value])
                else:
                    for old, new in ids.items():
                        value = value.replace(f"url(#{old})", f"url(#{new})")
                        if value == f"#{old}":
                            value = f"#{new}"
                    element.set(key, value)
        root.set("x", "0"); root.set("y", str(offset))
        root.set("width", str(box[2])); root.set("height", str(box[3]))
        combined.append(root)
        offset += box[3] + 12
    ET.ElementTree(combined).write(output, encoding="utf-8", xml_declaration=True)


def write_gallery(output, reports):
    sections = []
    for report in reports:
        scheme = report["scheme"]
        images = "".join(
            f'<figure><figcaption>第 {p["page"]}/{len(report["pages"])} 页 · {html.escape(" / ".join(p["stages"]))}</figcaption>'
            f'<a href="{scheme}/{p["svg"]}" target="_blank"><img loading="lazy" src="{scheme}/{p["svg"]}" alt="{scheme} page {p["page"]}"></a></figure>'
            for p in report["pages"])
        sections.append(f'<section id="{scheme}"><h2>{TITLES[scheme]}</h2>'
                        f'<p>{report["shown_wires"]} 条已使用 wire（分配 {report["allocated_wires"]} 条，未使用者省略） · {report["counts"]["measurement"]} 次测量 · '
                        f'{report["counts"].get("feedback", 0)} 个软件反馈更新 · '
                        f'<a href="{scheme}/complete.svg">完整 SVG</a> · '
                        f'<a href="{scheme}/source.stim">原始 Stim</a></p>{images}</section>')
    text = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>d=3 四种 syndrome extraction 线路</title><style>
body{font:16px/1.65 system-ui,sans-serif;margin:0;background:#f3f6fa;color:#203248}header,main{max-width:1400px;margin:auto;padding:24px}
header{padding-bottom:10px}h1{margin:0}nav{display:flex;gap:12px;flex-wrap:wrap;position:sticky;top:0;background:#f3f6fa;padding:12px 0;z-index:2}
a{color:#1769aa}nav a{background:white;padding:6px 15px;border:1px solid #d8e1eb;border-radius:8px;text-decoration:none}
section{scroll-margin-top:65px}figure{background:white;padding:15px;margin:20px 0;border:1px solid #d8e1eb;border-radius:10px;overflow:auto}
figcaption{color:#53657b;margin-bottom:10px}img{width:var(--zoom,100%);height:auto;min-width:850px;max-width:none}.note{border-left:4px solid #1769aa;padding:8px 18px;background:white}
</style><header><h1>d=3 · 四种 SE 线路</h1><p>Rotated surface code · 一轮完整 X/Z syndrome extraction · Qiskit 绘制</p>
<div class="note">输入边界是已有编码态：图中省略理想输入 encoder，且不做末尾 data readout。所有 SE 内部制备、测量及反馈均保留。Modified Steane 使用默认 prep_rounds=3。<br>
<b>D</b>：data；<b>A</b>：ancillary；<b>P/EA</b>：正在制备 / 已编码的辅助块；<b>F</b>：fresh layer；<b>free</b>：未占据。wire 随原子移动，不代表固定 trap。左侧/右侧标签分别表示该页入口/出口角色；A-slot/free 表示分配时属于辅助位置、当前没有原子。<br>
蓝色实心点与 ⊕ 为原生 CX；MZ/MX:m# 是带测量索引的 Z/X 读出；X/Z[m#] 为软件 Pauli frame；绿色方框表示角色/site 变化，<b>不是量子 SWAP 门</b>。<br>
空闲时刻和 DETECTOR/OBSERVABLE 注释不画成门；源数据、逐门来源及测量记录保存在各方案 JSON 与 source.stim。点击图片可单独打开 SVG 放大。</div>
</header><main><nav>'''
    text += "".join(f'<a href="#{r["scheme"]}">{TITLES[r["scheme"]]}</a>' for r in reports)
    text += '</nav><p><label>线路放大 <input aria-label="线路放大" type="range" min="100" max="350" step="25" value="100" oninput="document.documentElement.style.setProperty(\'--zoom\',this.value+\'%\');document.getElementById(\'zoom\').textContent=this.value+\'%\'"></label> <output id="zoom">100%</output>（放大后可在图片区域横向滚动）</p>' + "".join(sections) + '</main></html>'
    (output / "index.html").write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/se_circuits_d3"))
    parser.add_argument("--moments-per-page", type=int, default=16)
    args = parser.parse_args()
    if args.moments_per_page < 1:
        parser.error("moments-per-page must be positive")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "external/quantum-compiler/Quantum-compiler"))
    from se_circuits import build_se_circuit, surface_layout
    reports = []
    for scheme in ("swap", "mid_swap", "teleportation", "modified_steane"):
        program = build_se_circuit(scheme, 3, 1, final_measure=False)
        moments, annotations, counts = extract_moments(program)
        used = {q for m in moments for op in m["operations"] for q in op["wires"]} | set(program.initial_data)
        layout = surface_layout(3)
        sites = sorted(layout["coords"])
        # Group initial allocation by block, then data/check sites. Wire identity
        # remains fixed through all pages even when its current role changes.
        def order(q):
            block, local = divmod(q, len(sites))
            return block, sites[local] not in layout["data"], sites[local]
        wires = sorted(used, key=order)
        dest = args.output / scheme
        dest.mkdir(parents=True, exist_ok=True)
        chunks = [moments[i:i+args.moments_per_page] for i in range(0, len(moments), args.moments_per_page)]
        pages = [render_page(program, chunk, wires, i+1, len(chunks), dest, i*args.moments_per_page)
                 for i, chunk in enumerate(chunks)]
        combine_svg([dest / p["svg"] for p in pages], dest / "complete.svg")
        (dest / "source.stim").write_text(str(program.circuit), encoding="utf-8")
        metadata = {k: v for k, v in vars(program).items() if k != "circuit"}
        metadata.update({"drawing_moments": moments, "annotations": annotations,
                         "wire_order": wires, "omitted_unoccupied_wires": sorted(set(range(program.circuit.num_qubits))-used)})
        (dest / "source_map.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        report = {"scheme": scheme, "distance": 3, "rounds": 1, "prep_rounds": program.prep_rounds,
                  "shown_wires": len(wires), "allocated_wires": program.circuit.num_qubits,
                  "counts": dict(counts), "moments": len(moments), "pages": pages,
                  "initial_data": program.initial_data, "final_data": program.final_data,
                  "measurement_and_entangler_checks": "passed"}
        reports.append(report)
        print(f"{scheme}: {len(wires)} wires, {len(moments)} moments, {len(pages)} pages", flush=True)
    write_gallery(args.output, reports)
    (args.output / "manifest.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
