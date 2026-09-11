# FTQC Patch Rotation Compiler

面向中性原子平台 transversal Clifford 门的 surface-code patch rotation 优化原型。

## Jupyter 逐层编译演示

打开本目录的 [compiler_walkthrough.ipynb](compiler_walkthrough.ipynb)，可以查看项目架构图、
Processor 配置、输入与静态 Clifford 线路、G1/G2、插入 deformation 后的完整 DAG 和线路图、
Mapping、CZ blocks、全部 InstructionBlock、序列化校验及最终 AOD stage 图像。

使用 Python 3.11+，在本目录执行：

```bash
python -m pip install -e ".[notebook]"
python -m jupyterlab compiler_walkthrough.ipynb
```

选择安装上述依赖的 Python 内核，执行 Restart Kernel and Run All Cells。
Notebook 使用随附的 src，不依赖原项目绝对路径；运行生成的文件放在 outputs/notebook_demo。
执行过的 notebook 已内嵌图像输出，未运行时也可查看已有结果。源码快照不包含 external
基准数据集；本 notebook 不依赖这些数据，README 中涉及 external 的其他基准命令需另备数据。

## 功能

- 将 Qiskit Clifford 线路转为保留传递依赖的 G1/G2 DAG。
- 将 CNOT 展开为 `H-CZ-H`，计算 CZ 的初始共轭对齐状态。
- 随机端点翻转的 trivial 基线算法。
- 贪心 patch rotation 优化。
- 基于 Z3 和 horizon 二分搜索的最少 rotation 求解。
- 按拓扑层截取最多约 20 个 CZ 的滑动窗口 SAT 可扩展算法。
- 使用 CliffordOpt 生成两个随机 Clifford 子线路并拼接成深线路，比较 trivial、greedy 和 SAT 三种算法。
- 绘制插入 rotation 后的红/蓝 orientation 线路图。
- 输出保留全部 Clifford 门的编译 DAG；rotation 按优化调度位置插入，S 门以
  `folding-icz-S-unfolding` 展开，供下一层编译直接消费。`icz` 表示单个
  patch 内部的 CZ 操作，其物理比特操作数留待下一层编译确定。
- 可视化支持 H/S/X/Y/Z/CZ/CX（CX 预处理为 H-CZ-H）、rotation、folding、
  icz、unfolding；folding/icz/unfolding 不改变线路 orientation 颜色。

编译接口为 `compile_circuit(qiskit_circuit)`，返回的 `CompiledCircuit.dag` 是
NetworkX DAG；节点的 `operation` 属性为带 `kind/qubits/source_node` 的
`CompiledNode`。

## Processor 编译框架

已实现三 zone 几何、初始 Mapping、CZ/icz block、PowerMove 贪心着色与位置分配、
具有移动依赖的 AOD 分组和顺序调度。移动依赖形成环时，选择距离环内码块最近的
本轮未使用空闲 patch 作为缓冲区，并把缓冲移动计入 stage 数。

Python 入口：

```python
from ftqc_patch_rotation import Processor, ProcessorConfig, compile_processor

processor = Processor(ProcessorConfig(d=3, a1=4, b1=5, a2=3, b2=2))
logical_dag, schedule, metadata = compile_processor(circuit, processor, seed=0)
print(schedule.stage_count)
```

默认 site 间距 s=5 μm，pair pitch 为 2s，pair 内偏移 s/5，两个 zone 间距为 2s。
三个阵列左对齐；省略 L/H 时由阵列尺寸推导，显式提供时检查是否一致。
数据 patch 为 storage 上方一半行，辅助 patch 固定在下方区域。

生成 10-qubit、10-layer 示例及每个 AOD stage 的图片：

```powershell
C:\Users\lys\.conda\envs\py311\python.exe tools/compile_processor_example.py
```

编译已有静态 QASM：

```powershell
C:\Users\lys\.conda\envs\py311\python.exe tools/compile_processor_example.py --input benchmarks/feynman_clifford/tof_3.qasm --output outputs/framework/tof_3
```

输出 `compilation.json`（环境、完整 DAG、Mapping、BS、IB、最终位置和输入元数据）、
`summary.json`、逻辑线路图与 `stages/` 下的移动图。`save_compilation` 和
`load_compilation` 均执行独立重放校验。

T/CCX/CCZ 输入通过已有魔法态转换生成固定种子的静态分支；暂不支持动态经典控制、
SE 或 deformation 内部原子移动。`cost_fn` 是可替换的结果计分函数，默认统计 AOD
stage 数；PowerMove 的选择规则仍按开发方案执行，不因换计分函数自动变成最优搜索。
缓冲仅使用 storage data 和 entanglement 区；容量不足或没有合法空闲缓冲区时明确报错。

## 完整例子：配置环境、输入线路、查看各层 IR 和图片

可直接运行的脚本为 `tools/inspect_compiler_ir.py`。在项目根目录执行：

```powershell
C:\Users\lys\.conda\envs\py311\python.exe -X utf8 tools/inspect_compiler_ir.py
```

### 1. 配置 processor 并构造输入线路

脚本使用以下配置与线路：

```python
from qiskit import QuantumCircuit
from ftqc_patch_rotation import Processor, ProcessorConfig, compile_processor

processor = Processor(ProcessorConfig(
    d=3,
    a1=4, b1=5,   # storage/measurement：4 行、5 列 patch
    a2=3, b2=2,   # entanglement：2 行、每行 3 个 patch pair
    s=5,                         # storage/measurement site 间距，单位 μm
    pair_pitch_x=10, pair_pitch_y=10,
    pair_offset=1,               # 同一 site pair 内的水平间距
    gap_se=10, gap_em=10,        # 相邻 zone 最近 site 行的距离
    L=81, H=180,                 # 与阵列规模及间距相容；也可以省略以自动推导
))

circuit = QuantumCircuit(3)
circuit.h(0)
circuit.t(0)
circuit.ccz(0, 1, 2)
circuit.s(1)
circuit.cx(1, 2)
circuit.reset(0)
circuit.cz(0, 2)

compiled, schedule, metadata = compile_processor(circuit, processor, seed=7)
```

初始输入有 3 个逻辑比特，魔法态转换增加 4 个资源逻辑比特，共 7 个。
此环境有 10 个 data patch 和 10 个 ancilla patch，容量足够。
`seed=7` 固定测量分支采样及路由中的随机选择。

### 2. 查看各层 IR

接着运行下列代码，或直接查看脚本的终端输出：

```python
from qiskit import qasm2
from ftqc_patch_rotation import preprocess

# 输入线路 IR：Qiskit QuantumCircuit
print(circuit.draw(output="text"))

# 魔法态转换后的静态 Clifford IR：QASM → QuantumCircuit
clifford = qasm2.loads(metadata["static_trace_qasm"])
print(clifford.draw(output="text"))

# 优化内部 IR：G1 保留全部门，G2 仅保留 CZ 与投影依赖
prepared = preprocess(clifford)  # 为查看而重建，不会再次编译或插入 rotation
print(list(prepared.g1.nodes(data=True)))
print(list(prepared.g2.edges))

# 编译后逻辑 DAG：包含 rot、folding、icz、S、unfolding
print(compiled.rotations)
print(list(compiled.operations()))
print(list(compiled.dag.edges))

# 路由调度 IR：初始位置、CZ block、按执行顺序排列的 IB
print(schedule.mapping)
print(schedule.cz_blocks)
for index, ib in enumerate(schedule.blocks):
    print(index, ib.kind, ib.nodes, ib.moves)
print(schedule.final_positions)
print("AOD stage 数：", schedule.stage_count)
```

`ib.nodes` 引用 `compiled.dag` 中的节点 ID；AOD IB 的 `ib.moves` 给出
`qubit/start/target`。同一个 AOD IB 中的 Move 并行执行，IB 之间按列表顺序执行。

### 3. 保存、重新加载与生成图片

```python
from pathlib import Path
from ftqc_patch_rotation import save_compilation, load_compilation
from ftqc_patch_rotation.visualize import draw_compiled_circuit
from ftqc_patch_rotation.hardware_visualize import draw_hardware_schedule

output = Path("outputs/framework/ir_walkthrough")
path = save_compilation(output / "compilation.json",
                        compiled, processor, schedule, metadata)
loaded_dag, loaded_processor, loaded_schedule, loaded_metadata = load_compilation(path)
# save/load 都会执行重放校验，失败时抛出异常。

draw_compiled_circuit(compiled, output / "logical_circuit.png")
draw_hardware_schedule(processor, schedule, output / "stages")
```

完整脚本还会保存输入 QASM、Clifford QASM 和 G1/G2，输出如下：

| 文件（位于 `outputs/framework/ir_walkthrough/`） | 查看内容 |
| --- | --- |
| `input.qasm` | 转换前的输入线路 |
| `clifford.qasm` | 包含魔法态资源、测量和 reset 的静态 Clifford 线路 |
| `g1.json`、`g2.json` | 优化阶段的节点与边 |
| `compilation.json` | `processor`、`circuit`、`schedule`、`metadata` 和校验结果 |
| `logical_circuit.png` | 插入 rotation、folding、icz、unfolding 后的逻辑线路 |
| `stages/initial_mapping.png` | 初始数据码块及辅助码块位置 |
| `stages/stage_001.png` 等 | 每个 AOD stage 的起点、目标与移动箭头 |
| `stages/overview_01.png` 等 | 每页六幅图的移动过程总览 |
| `stages/final_mapping.png` | 全部指令结束后的最终位置 |

在编辑器中打开上述 JSON/PNG 即可查看。硬件移动图中，彩色半透明矩形覆盖数据码块的
整个 patch，灰色半透明矩形覆盖固定辅助码块的 patch，箭头连接起止 patch 的中心，
无填充虚线矩形框住目标 patch。矩形边界取最外侧 site 的坐标，不额外增加留白。
这些图展示 patch 级移动，不是 deformation 内部的物理原子轨迹。

## 测试

```powershell
C:\Users\lys\.conda\envs\py311\python.exe -m pytest -q
```

## 随机实验

先以开发模式安装本项目：

```powershell
C:\Users\lys\.conda\envs\py311\python.exe -m pip install -e .
```

运行计划中的 10 个 10-qubit 实验：

```powershell
C:\Users\lys\.conda\envs\py311\python.exe -m ftqc_patch_rotation.experiment `
  --output results_deep --count 10 --qubits 10 --segments 10 `
  --window-size 20 --timeout 60 --seed 0
```

未拼接（每条仅一个 CliffordOpt 线路）的实验增加 `--segments 1`。

结果目录包含 QASM、rotation 序列、CSV、算法对比图，以及首条线路的可视化图。

## Feynman Clifford 测试集

原始仓库位于 `external/feynman`。以下命令把其中的 QASM 线路转换到
`benchmarks/feynman_clifford`：CCX 先展开成 H-CCZ-H，CCZ 和 T/Tdg 再通过
`CCZReg[3]`、`TReg[1]` 魔法态注入（OpenQASM 2 文件中按语法要求写成小写
`cczreg`、`treg`，声明旁保留逻辑名称）；测量分支由固定种子采样并写入注释及
`manifest.json`，因而结果可复现。

```powershell
python tools/convert_feynman_clifford.py --seed 20260826
```

资源寄存器在每次使用后显式 reset。预处理器、greedy 和 Z3 求解器均把 reset
视为新的 rotation epoch，重置后的 `rot` 为 0，之前的 patch rotation 不会传播
到下一份资源态。
