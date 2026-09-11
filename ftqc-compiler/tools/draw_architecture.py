"""Export a readable, code-native architecture diagram as PNG and SVG."""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams.update({'font.family': 'Microsoft YaHei', 'svg.fonttype': 'path'})
fig, ax = plt.subplots(figsize=(22, 19))
fig.patch.set_facecolor('white')
ax.set(xlim=(0, 22), ylim=(0, 19))
ax.axis('off')
blue, orange, ink = '#25638e', '#b27621', '#233545'

def box(x, y, w, h, title, body, future=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.025,rounding_size=0.12',
        facecolor='#fff5e5' if future else '#edf5fa', edgecolor=orange if future else blue,
        linewidth=1.3, linestyle='--' if future else '-'))
    ax.text(x+w/2, y+h-0.23, title, ha='center', va='top', fontsize=15,
            weight='bold', color=ink)
    ax.text(x+w/2, y+(h-0.35)/2, body, ha='center', va='center', fontsize=12,
            color=ink, linespacing=1.65)

def arrow(points, dashed=False):
    for a,b in zip(points[:-2], points[1:-1]):
        ax.plot([a[0],b[0]], [a[1],b[1]], color=orange if dashed else blue,
                lw=1.4, ls='--' if dashed else '-')
    ax.add_patch(FancyArrowPatch(points[-2],points[-1],arrowstyle='-|>',mutation_scale=15,
        color=orange if dashed else blue,lw=1.4,linestyle='--' if dashed else '-'))

ax.text(0.6,18.5,'容错中性原子编译器 · 项目架构',fontsize=25,weight='bold',color=ink)
ax.text(0.6,18.0,'实线：已实现流程 / 接口     橙色虚线：未来接入关系；模块待实现',fontsize=13,color=ink)
for x,title in [(0.6,'环境与可扩展接口'),(7.6,'当前编译主流程'),(15.0,'未来下层编译 · 待实现')]:
    ax.text(x,17.35,title,fontsize=18,weight='bold',color=ink)

box(7.6,15.7,6.2,1.25,'输入与端到端入口','QuantumCircuit / OpenQASM 2\ncompile_processor · pipeline.py')
box(7.6,13.85,6.2,1.5,'静态前端 → 预处理','magic_states.py：T / CCZ → Clifford trace\npreprocess.py：CX 展开；完整 G1 / CZ 投影 G2')
box(7.6,12.05,6.2,1.45,'Rotation 优化与辅助操作插入','Trivial / Greedy / SAT / Window SAT\nS → folding → icz → S → unfolding；插入 rot')
box(7.6,10.2,6.2,1.5,'逻辑 IR · CompiledCircuit','NetworkX DAG + CompiledNode\nid / kind / qubits / source_node / reset_epochs')
box(7.6,6.65,6.2,3.2,'空间编译 · routing.py','build_cz_blocks + initial_mapping\n普通指令优先 → deformation → CZ/icz\npartition_block：贪心着色与 pair 容量\nassign_positions：PowerMove + 二维最近空位\nplan_aod_stages：依赖、环缓冲、非交叉分组\n更新位置并记录 IB；循环至所有指令完成')
box(7.6,4.8,6.2,1.5,'空间 IR · RoutingSchedule','Mapping + BS + InstructionBlock 序列\nMove / 最终位置 / cost')
box(7.6,3.05,6.2,1.4,'独立重放校验 · validate_schedule','指令依赖与优先级 / pair 资源\n移动合法性 / 最终状态')
box(7.6,0.85,6.2,1.85,'输出与可视化','save_compilation / load_compilation：JSON\nvisualize.py：逻辑线路图（读取逻辑 DAG）\nhardware_visualize.py：布局与逐 AOD stage 图')
for top,bottom in [(15.7,15.35),(13.85,13.5),(12.05,11.7),(10.2,9.85),(6.65,6.3),(4.8,4.45),(3.05,2.7)]:
    arrow([(10.7,top),(10.7,bottom)])

box(0.6,12.1,5.8,1.4,'已有接口 · optimizer(prepared)','替换 rotation 优化策略\n返回 rotation 插入位置')
arrow([(6.4,12.8),(7.6,12.8)])
box(0.6,8.3,5.8,2.2,'Processor 环境 · hardware.py','ProcessorConfig → Processor\nzone / site / patch / patch pair 几何\nsite_position / patch_sites / pair_members\n供 Mapping、位置分配、AOD、校验与绘图使用')
arrow([(6.4,9.0),(7.6,9.0)])
box(0.6,6.3,5.8,1.35,'已有接口 · mapping=None','可传入初始 Mapping\n数据码块后续位置可变化；辅助码块固定')
arrow([(6.4,7.1),(7.6,7.1)])
box(0.6,4.45,5.8,1.5,'已有接口 · cost_fn(stages)','默认 len：统计 AOD stage 总数\n替换此函数不会自动改变规划策略')
arrow([(6.4,5.5),(7.6,5.5)])
box(0.6,1.5,5.8,2.0,'实现边界','路由步骤集中于 routing.py 中的函数\n并非多个 Planner / Provider 框架模块\n内部移动与二次调度仅保留数据接入边界\n当前没有对应的插件接口或空接口类')

box(15,14.1,6.3,2.0,'待实现 · 完整资源态运行流程','魔法态工厂 / 资源态制备\n真实测量反馈与动态经典分支\n当前前端仅产生选定分支的静态 trace',True)
arrow([(13.8,14.6),(15,14.6)],True)
box(15,10.05,6.3,2.2,'待实现 · 码块内部 lowering','rot / folding / unfolding 的内部原子移动\nicz 的物理操作数与内部 CZ 展开\n接入：逻辑 DAG + deformation IB + 位置\n几何：复用 Processor 的 site / patch 接口',True)
arrow([(13.8,10.95),(15,10.95)],True)
arrow([(13.8,5.8),(14.4,5.8),(14.4,10.35),(15,10.35)],True)
box(15,7.45,6.3,1.8,'待实现 · 空间约束与二次调度','对展开后的 deformation 建模\n满足空间约束时优化多个码块的并行执行',True)
arrow([(18.15,10.05),(18.15,9.25)],True)
box(15,4.3,6.3,1.8,'待实现 · Syndrome Extraction','辅助码块动态搬运与纠错流程\n接入：已有固定 ancilla Mapping 与几何',True)
arrow([(13.8,5.2),(15,5.2)],True)
box(15,0.85,6.3,2.05,'待实现 · 耗时模型与时间轴优化','综合物理操作与移动耗时\n结合内部调度、SE、资源态流程\n产生更低层执行序列；支持新的优化目标',True)
arrow([(18.15,4.3),(18.15,2.9)],True)
arrow([(21.3,8.3),(21.7,8.3),(21.7,1.85),(21.3,1.85)],True)
arrow([(21.3,15.1),(21.9,15.1),(21.9,1.35),(21.3,1.35)],True)

out = Path(__file__).resolve().parents[1]
fig.savefig(out/'项目架构图.png',dpi=260,facecolor='white')
fig.savefig(out/'项目架构图.svg',facecolor='white')
print(out/'项目架构图.png')
print(out/'项目架构图.svg')
