"""Static processor layout and per-AOD-stage movement figures."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from .routing import apply_stage


def _patch_bounds(processor, patch):
    """Bounds from the bottom-left to the top-right site, without padding."""
    x, y = map(float, processor.patch_anchor(patch))
    last = processor.config.d - 1
    right, top = map(float, processor.site_position((patch, last, last)))
    return x, y, right - x, top - y


def _draw(ax, processor, pos, ancilla, title, moves=()):
    s = float(processor.s)
    for zone, color in (("storage", "#dceeff"), ("entanglement", "#fff0d9"), ("measurement", "#e8e4f5")):
        patches = [p for p in processor.patches.values() if p.zone == zone]
        coords = [processor.site_position(site) for p in patches for site in processor.patch_sites(p.id)]
        xs, ys = zip(*[(float(x), float(y)) for x, y in coords])
        ax.add_patch(Rectangle((-s/2, min(ys)-s/2), float(processor.L)+s, max(ys)-min(ys)+s,
                               facecolor=color, edgecolor="#aaaaaa", lw=0.6, zorder=0))
        ax.scatter(xs, ys, s=1, c="#888888", alpha=0.45)
        ax.text(float(processor.L)+s, (min(ys)+max(ys))/2, zone, rotation=90,
                va="center", fontsize=8, color="#555555")
    for q, p in ancilla.items():
        x,y,w,h = _patch_bounds(processor, p)
        ax.add_patch(Rectangle((x,y), w,h, facecolor=(0.65,0.70,0.75,0.30),
                               edgecolor="#7e8b97", lw=0.7, zorder=4))
        ax.text(x+w/2,y+h/2,f"a{q}",ha="center",va="center",fontsize=6,zorder=7)
    for q, p in pos.items():
        x,y,w,h = _patch_bounds(processor, p)
        color = plt.get_cmap("tab10")(q % 10)
        ax.add_patch(Rectangle((x,y),w,h,facecolor=(*color[:3],0.25),
                               edgecolor=color,lw=1.0,zorder=5))
        # Stagger labels vertically when two nearly overlapping patches pair.
        member = processor.patches[p].member
        fraction = 0.7 if member == 0 else 0.3 if member == 1 else 0.5
        ax.text(x+w/2,y+h*fraction,f"q{q}",ha="center",va="center",fontsize=7,zorder=7)
    for move in moves:
        x,y,w,h = _patch_bounds(processor, move.start)
        u,v,tw,th = _patch_bounds(processor, move.target)
        color = plt.get_cmap("tab10")(move.qubit % 10)
        ax.annotate("", xy=(u+tw/2,v+th/2), xytext=(x+w/2,y+h/2),
                    arrowprops=dict(arrowstyle="->", lw=1.7,color=color), zorder=6)
        ax.add_patch(Rectangle((u,v),tw,th,fill=False,edgecolor=color,
                               linestyle="--",lw=1.5,zorder=6))
    ax.set_title(title, fontsize=10)
    ax.set_aspect("equal")
    ax.set_xlim(-2*s, float(processor.L)+3*s)
    ax.set_ylim(-s, float(processor.H)+2*s)
    ax.set_xlabel("x (um)", fontsize=8)
    ax.set_ylabel("y (um)", fontsize=8)
    ax.tick_params(labelsize=7)


def draw_hardware_schedule(processor, schedule, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    pos = schedule.mapping.initial_data_patch.copy()
    frames = [("Initial mapping", pos.copy(), ())]
    for block in schedule.blocks:
        if block.kind == "aod":
            frames.append((f"AOD stage {len(frames)} | {len(block.moves)} moves", pos.copy(), block.moves))
            apply_stage(pos, block.moves, processor)
    frames.append(("Final placement", pos.copy(), ()))
    files = []
    for index, (title, state, moves) in enumerate(frames):
        fig, ax = plt.subplots(figsize=(7,8))
        _draw(ax, processor, state, schedule.mapping.ancilla_patch, title, moves)
        fig.tight_layout()
        path = output / ("initial_mapping.png" if index == 0 else "final_mapping.png" if index == len(frames)-1 else f"stage_{index:03d}.png")
        fig.savefig(path, dpi=150)
        plt.close(fig)
        files.append(path)
    for start in range(0,len(frames),6):
        fig, axes = plt.subplots(2,3,figsize=(15,12))
        for ax, item in zip(axes.flat, frames[start:start+6]):
            _draw(ax, processor, item[1], schedule.mapping.ancilla_patch, item[0], item[2])
        for ax in list(axes.flat)[len(frames[start:start+6]):]:
            ax.axis("off")
        fig.tight_layout()
        fig.savefig(output/f"overview_{start//6+1:02d}.png", dpi=140)
        plt.close(fig)
    return files
