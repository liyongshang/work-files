"""Offline SVG replay and static overview of validated atom-level SE passes."""
import json
from pathlib import Path

from ftqc_patch_rotation.passes.se import validate_se_program
from ftqc_patch_rotation.passes.se.aod import pickup_grid


NAMES = {
    "approach": "AQ 接近 DQ",
    "entangle": "执行邻居纠缠宏",
    "restore_far_strips": "先还原远离边界的行/列",
    "restore_near_strip": "单独还原紧邻边界的一行/列",
    "exchange_roles_and_homes": "交换配对原子的角色及所属 patch",
    "restore_paired_old_D": "还原已配对的原 DQ（现为 A）",
    "transfer_boundary_old_D": "转移未配对的原 DQ（仍为 D）",
    "transfer_boundary_old_A": "转移未配对的原 AQ（仍为 A）",
}


def visualization_data(processor, program):
    frames = validate_se_program(processor, program)
    sites = []
    for patch in (program.initial.data_patch, program.initial.ancilla_patch):
        for site in processor.patch_sites(patch):
            x, y = processor.site_position(site)
            sites.append(dict(patch=patch, row=site[1]+1, col=site[2]+1, x=float(x), y=float(y)))
    views = []
    for i, state in enumerate(frames):
        op = program.instructions[i-1] if i else None
        view = dict(title="初始棋盘格装载" if op is None else NAMES[op.name],
                    direction="START" if op is None else op.direction,
                    kind="initial" if op is None else op.kind,
                    data_patch=state.data_patch, ancilla_patch=state.ancilla_patch,
                    atoms=[dict(id=a.id, role=a.role, x=float(a.x), y=float(a.y))
                           for a in state.atoms.values()],
                    moving=[], pairs=[], traps=[], starts=[], delta=[0, 0], detail="")
        if op and op.kind == "aod":
            before = frames[i-1]
            xs, ys, caught = pickup_grid(before, op.atoms)
            view.update(moving=list(op.atoms), delta=[float(v) for v in op.delta],
                        traps=[[float(x), float(y)] for x in sorted(xs) for y in sorted(ys)],
                        starts=[dict(id=q, x=float(before.atoms[q].x), y=float(before.atoms[q].y))
                                for q in op.atoms],
                        detail=f"{len(xs)} 条 x 线 × {len(ys)} 条 y 线 = {len(xs)*len(ys)} 个势阱；"
                               f"抓取 {len(caught)} 个原子，误抓 0 个。")
        elif op and op.kind in ("entangle", "roles"):
            view["pairs"] = [list(pair) for pair in op.pairs]
            view["detail"] = (f"{len(op.pairs)} 对邻居；每对的间距为 pair_offset。"
                              if op.kind == "entangle" else
                              f"{2*len(op.pairs)} 个原子交换 D/A 角色；边界原子保持角色。"
                              "本步只更新语义，后续三次移动恢复棋盘格。")
        else:
            view["detail"] = "DQ 占偶数奇偶格，AQ 占互补格；行、列编号从 1 开始。"
        views.append(view)
    return dict(distance=program.distance, grid_size=processor.site_grid_size,
                aod_stages=program.aod_stages, sites=sites, frames=views)


def draw_se_overview(processor, program, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    payload = visualization_data(processor, program)
    frames = payload["frames"]
    indices = [0] + [i for i, f in enumerate(frames) if f["kind"] == "entangle"] + [len(frames)-1]
    fig, axes = plt.subplots(2, 3, figsize=(15, 10), layout="constrained")
    x0 = min(s["x"] for s in payload["sites"])
    y0 = min(s["y"] for s in payload["sites"])
    for ax, index in zip(axes.flat, indices):
        view = frames[index]
        lookup = {a["id"]: a for a in view["atoms"]}
        for site in payload["sites"]:
            ax.plot(site["x"]-x0, site["y"]-y0, ".", color="#d6dce5", ms=3, zorder=1)
        for dq, aq in view["pairs"]:
            d, a = lookup[dq], lookup[aq]
            ax.plot([d["x"]-x0, a["x"]-x0], [d["y"]-y0, a["y"]-y0],
                    color="#af4be3", lw=4, zorder=2)
        for role, color in (("D", "#176bd4"), ("A", "#d1840b")):
            atoms = [a for a in view["atoms"] if a["role"] == role]
            ax.scatter([a["x"]-x0 for a in atoms], [a["y"]-y0 for a in atoms],
                       s=38, c=color, edgecolors="white", linewidths=.5, zorder=3)
        title = "Initial: 13 D + 12 A" if index == 0 else (
            "Final: homes exchanged" if index == len(frames)-1 else f"{view['direction']}: 10 entangling pairs")
        if program.distance != 3:
            title = "Initial occupancy" if index == 0 else (
                "Final occupancy" if index == len(frames)-1 else f"{view['direction']}: {len(view['pairs'])} entangling pairs")
        ax.set_title(title, loc="left", fontsize=12, weight="bold")
        ax.set_aspect("equal")
        ax.set_xlim(-4, (processor.site_grid_size-1)*float(processor.px)+5)
        ax.set_ylim((processor.site_grid_size-1)*float(processor.py)+4, -4)
        ax.set_xlabel("x from pair origin (um)")
        ax.set_ylabel("y from pair origin (um)")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(alpha=.12)
    fig.suptitle(f"Non-rotated surface code d={program.distance} | LRUD SE motion | "
                 f"{program.aod_stages} AOD moves\n"
                 "Blue: current data role   Amber: current ancilla role   Purple: entangling macro",
                 fontsize=17, weight="bold")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    fig.savefig(path.with_suffix(".svg"))
    plt.close(fig)
    return path


def write_se_replay(processor, program, path):
    payload = json.dumps(visualization_data(processor, program), ensure_ascii=False).replace("</", "<\\/")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HTML.replace("__PAYLOAD__", payload), encoding="utf-8")
    return path


HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SE passes · LRUD atom replay</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#162a45;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}
header{background:#142840;color:white;padding:26px max(24px,calc((100vw - 1360px)/2))}
header small{color:#98b6da;letter-spacing:.18em}h1{margin:6px 0;font-size:29px}header p{margin:0;color:#cad9e8}
main{max-width:1408px;margin:auto;padding:24px}.stats{display:flex;gap:12px;margin-bottom:18px;flex-wrap:wrap}
.stat{background:white;border:1px solid #dce5ef;border-radius:10px;padding:12px 20px;flex:1;min-width:135px}.stat b{font-size:24px;margin-right:10px}
.layout{display:grid;grid-template-columns:minmax(550px,1fr) 350px;gap:20px}.card{background:white;border:1px solid #dce5ef;border-radius:14px;padding:20px}
.controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap}button,select{font:inherit;border:1px solid #cbd7e4;background:white;color:#203e61;border-radius:6px;padding:6px 12px;cursor:pointer}button:hover{background:#eaf2ff}
button.active,#play{background:#205cba;color:white;border-color:#205cba}button:disabled{opacity:.4;cursor:default}input[type=range]{width:100%;accent-color:#205cba}
h2{font-size:20px;margin:0 0 12px}h3{font-size:16px;margin:18px 0 8px}.muted{color:#677c93;font-size:13px}.legend{display:flex;flex-wrap:wrap;gap:15px;margin-top:10px;font-size:13px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
#map{width:100%;min-height:450px;display:block;background:#fbfcfe;border-radius:10px;margin-top:14px}.note{background:#edf4ff;border-left:3px solid #4d80ca;padding:12px;font-size:14px;margin-top:16px}
.homes{font:12px/1.8 ui-monospace,monospace;overflow-wrap:anywhere;background:#f5f7fa;padding:12px;border-radius:8px}.step-list{max-height:370px;overflow:auto;display:grid;gap:5px}.step-list button{text-align:left;font-size:12px;padding:6px 9px}
.phase{display:flex;gap:6px;margin:14px 0}a{color:#205cba}.foot{margin-top:20px;color:#687b90;font-size:13px}label{font-size:13px}#count{margin-left:auto;white-space:nowrap}
@media(max-width:980px){.layout{grid-template-columns:1fr}header{padding:22px}.step-list{max-height:220px}}
</style></head><body>
<header><small>COMPILER / SYNDROME EXTRACTION</small><h1>LRUD · 码块内部原子移动</h1>
<p>非旋转 surface code · 稀疏棋盘格装载 · D 阶段交换 data / ancilla 角色</p></header>
<main><div class="stats"><div class="stat"><b id="distance"></b>码距</div><div class="stat"><b id="grid"></b>site 网格 / patch</div><div class="stat"><b id="population"></b>DQ + AQ</div><div class="stat"><b id="moves"></b>AOD 移动</div></div>
<div class="layout"><section class="card"><div class="controls"><button id="prev">← 上一步</button><button id="play">播放</button><button id="next">下一步 →</button><span id="count"></span></div>
<input id="slider" type="range" min="0" value="0" aria-label="回放步骤">
<div class="phase" id="phases"></div><h2 id="title"></h2><div id="detail"></div>
<svg id="map" viewBox="0 0 760 610" role="img" aria-label="DQ AQ 精确坐标及 AOD 势阱回放"></svg>
<div class="legend"><span><i class="dot" style="background:#176bd4"></i>D 当前数据角色</span><span><i class="dot" style="background:#d1840b"></i>A 当前辅助角色</span><span><i class="dot" style="background:#1aa989"></i>本步移动原子</span><span><i class="dot" style="background:#ad4cd2"></i>纠缠配对</span></div>
<div class="controls" style="margin-top:14px"><label><input type="checkbox" id="traps" checked>显示抓取时完整 AOD 阵列</label><label><input type="checkbox" id="ids">显示原子 ID</label></div>
<p class="muted">图示为每一步完成后的状态；绿色箭头表示位移，浅绿叉号表示移动前的势阱位置。坐标保持真实比例，y 向下为 D。悬停查看原子 ID、当前角色和坐标。</p>
</section><aside class="card"><h2>Pass 回放</h2><div class="homes" id="homes"></div>
<div class="note" id="explanation"></div><h3>全部步骤</h3><div id="steps" class="step-list"></div>
<h3>为什么还原要拆两次？</h3><p class="muted">AQ 移动后，紧邻边界的行/列与未移动边界共用一个坐标。一次抓取所有待还原原子时，完整 x × y 阵列会抓到边界原子。先还原远处，再只抓一行/列，可避免误抓。</p>
<p class="muted">D 阶段：配对原子交换角色并交换 home patch；随后移动已配对的原 DQ，再分别跨 pair_offset 转移两组未配对边界原子。</p>
<a href="overview.png">查看静态总览 PNG</a> · <a href="program.json">精确坐标与指令 JSON</a></aside></div>
<div class="foot">本示例展示 SE 移动 passes。ENTANGLE 与角色交换为语义宏；尚未展开具体量子门、初始化/测量及 Pauli frame。校验覆盖完整阵列抓取、终点不重叠、邻居覆盖与角色/位置还原；不表示已验证连续移动轨迹或硬件耗时。页面数据内嵌，可直接离线打开。</div>
</main><script>
const data=__PAYLOAD__;
const $=id=>document.getElementById(id), frames=data.frames;
let index=0,timer=null;
const colors={D:'#176bd4',A:'#d1840b'};
$('distance').textContent=data.distance;$('grid').textContent=`${data.grid_size}×${data.grid_size}`;
$('population').textContent=frames[0].atoms.filter(a=>a.role==='D').length+' + '+frames[0].atoms.filter(a=>a.role==='A').length;
$('moves').textContent=data.aod_stages;$('slider').max=frames.length-1;
const minX=Math.min(...data.sites.map(s=>s.x)),minY=Math.min(...data.sites.map(s=>s.y));
const maxX=Math.max(...data.sites.map(s=>s.x)),maxY=Math.max(...data.sites.map(s=>s.y));
const scale=Math.min(620/(maxX-minX+10),510/(maxY-minY+10));
const X=x=>80+(x-minX+4)*scale,Y=y=>35+(y-minY+4)*scale;
function line(x1,y1,x2,y2,extra=''){return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" ${extra}/>`}
frames.forEach((f,i)=>{let b=document.createElement('button');b.textContent=`${String(i).padStart(2,'0')}  ${f.direction} · ${f.title}`;b.onclick=()=>{stop();render(i)};$('steps').append(b)});
['START','L','R','U','D'].forEach(d=>{let b=document.createElement('button');b.textContent=d;b.onclick=()=>{stop();render(frames.findIndex(f=>f.direction===d))};$('phases').append(b)});
function render(i){index=i;const f=frames[i],byId=Object.fromEntries(f.atoms.map(a=>[a.id,a]));
$('slider').value=i;$('count').textContent=`${i} / ${frames.length-1}`;$('title').textContent=`${f.direction} · ${f.title}`;$('detail').textContent=f.detail;
$('prev').disabled=i===0;$('next').disabled=i===frames.length-1;
$('homes').textContent=`Data home: ${f.data_patch}\nAncilla home: ${f.ancilla_patch}`;$('homes').style.whiteSpace='pre-wrap';
$('explanation').textContent=f.kind==='aod'?`本次平移 Δx=${f.delta[0]} μm，Δy=${f.delta[1]} μm。空势阱仍是完整阵列的一部分。`:f.kind==='roles'?'原子 ID 保持不变；颜色随当前角色改变。此时位置尚未还原。':'原子 ID 的 D/A 前缀只表示初始来源，当前角色以颜色和悬停信息为准。';
Array.from($('steps').children).forEach((b,j)=>b.classList.toggle('active',j===i));
Array.from($('phases').children).forEach(b=>b.classList.toggle('active',b.textContent===f.direction));
let svg=`<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10" fill="#159879"/></marker></defs>`;
for(let r=0;r<data.grid_size;r++){const s=data.sites.find(s=>s.row===r+1);svg+=`<text x="35" y="${Y(s.y)+4}" fill="#7b8ca1" font-size="12">行 ${r+1}</text>`}
for(let c=0;c<data.grid_size;c++){const s=data.sites.find(s=>s.col===c+1);svg+=`<text x="${X(s.x)}" y="${Y(minY)-23}" fill="#7b8ca1" font-size="12" text-anchor="middle">列 ${c+1}</text>`}
data.sites.forEach(s=>svg+=`<circle cx="${X(s.x)}" cy="${Y(s.y)}" r="2.5" fill="#d9e0ea"/>`);
if($('traps').checked&&f.traps.length){const xs=[...new Set(f.traps.map(p=>p[0]))],ys=[...new Set(f.traps.map(p=>p[1]))];
xs.forEach(x=>svg+=line(X(x),Y(Math.min(...ys))-10,X(x),Y(Math.max(...ys))+10,'stroke="#9bd6c6" stroke-dasharray="3 5"'));
ys.forEach(y=>svg+=line(X(Math.min(...xs))-10,Y(y),X(Math.max(...xs))+10,Y(y),'stroke="#9bd6c6" stroke-dasharray="3 5"'));
f.traps.forEach(([x,y])=>{svg+=line(X(x)-3,Y(y)-3,X(x)+3,Y(y)+3,'stroke="#66bca5"');svg+=line(X(x)-3,Y(y)+3,X(x)+3,Y(y)-3,'stroke="#66bca5"')});}
f.starts.forEach(a=>{let b=byId[a.id];svg+=line(X(a.x),Y(a.y),X(b.x),Y(b.y),'stroke="#159879" stroke-width="1.5" opacity=".65" marker-end="url(#arrow)"')});
f.pairs.forEach(([d,a])=>svg+=line(X(byId[d].x),Y(byId[d].y),X(byId[a].x),Y(byId[a].y),'stroke="#ad4cd2" stroke-width="4"'));
f.atoms.forEach(a=>{const moving=f.moving.includes(a.id);if(moving)svg+=`<circle cx="${X(a.x)}" cy="${Y(a.y)}" r="8" fill="none" stroke="#1aa989" stroke-width="1.6"/>`;
svg+=`<circle cx="${X(a.x)}" cy="${Y(a.y)}" r="5" fill="${colors[a.role]}" stroke="white" stroke-width=".7"><title>${a.id} | 当前 ${a.role} | (${a.x}, ${a.y}) μm</title></circle>`;
if($('ids').checked)svg+=`<text x="${X(a.x)}" y="${Y(a.y)+(a.id.startsWith('D')?-12:22)}" text-anchor="middle" font-size="9" fill="${colors[a.role]}">${a.id}</text>`;});
svg+=`<text x="80" y="590" fill="#7b8ca1" font-size="12">坐标原点 (${minX}, ${minY}) μm · 两个 patch 的 site 交错相邻显示</text>`;
$('map').innerHTML=svg;}
function stop(){if(timer)clearInterval(timer);timer=null;$('play').textContent='播放'}
$('prev').onclick=()=>{stop();render(Math.max(0,index-1))};$('next').onclick=()=>{stop();render(Math.min(frames.length-1,index+1))};
$('slider').oninput=e=>{stop();render(+e.target.value)};$('traps').onchange=$('ids').onchange=()=>render(index);
$('play').onclick=()=>{if(timer){stop();return}if(index===frames.length-1)render(0);$('play').textContent='暂停';timer=setInterval(()=>{if(index===frames.length-1)stop();else render(index+1)},1400)};
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT')return;if(e.key==='ArrowRight')$('next').click();if(e.key==='ArrowLeft')$('prev').click()});render(0);
</script></body></html>'''
