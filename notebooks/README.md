# NAQsim 逐 Pass 编译 Demo

打开 [`naqsim_pass_demo.ipynb`](naqsim_pass_demo.ipynb)，从上到下运行全部单元格。Notebook 使用一条小型三比特线路，展示上游 NAQsim 的五个模块各自接收的输入、产生的输出，以及对应的数据表和图。

[`demo_visualization.py`](demo_visualization.py) 提供展示函数；编译和调度仍调用 `../src/tsc_naa_sim/` 中的原始实现。

## 内核与运行方式

使用 **conda 环境 `py311`**，选择与该环境对应的 Jupyter Python 内核。环境名称不决定 Python 的版本；Notebook 会显示并检查实际解释器路径和版本。

`py311` 已按确认升级到 **Python 3.13.14**，满足上游 `pyproject.toml` 的 Python ≥ 3.13 要求；内核名称仍为 `py311`。原环境为 Python 3.12.13。本次仅迁移 demo 所需依赖，其余二进制包的状态见 [环境记录](environment_py311.md)。

在终端检查环境：

```powershell
conda activate py311
python -c "import sys; print(sys.executable); print(sys.version)"
python -c "import qiskit, numpy, pandas, scipy, rustworkx, matplotlib, ipykernel, nbformat, jupyter_client; print('Demo dependencies available')"
```

在 VS Code 或已有的 Jupyter 前端打开 Notebook，选择 `py311` 对应的内核，然后运行全部单元格。若前端尚未发现该环境，可在激活 `py311` 后注册内核：

```powershell
python -m ipykernel install --user --name py311 --display-name "Python (py311)"
```

Demo 的最小依赖为 `qiskit`、`numpy`、`pandas`、`scipy`、`rustworkx`、`matplotlib`、`ipykernel`、`nbformat` 和 `jupyter-client`。不需要 Graphviz、Plotly、zstandard 或 nbclient，也不需要安装整个上游项目。Notebook 直接加载本地源码；请保留 `notebooks/` 与 `src/tsc_naa_sim/` 的相对位置。

## 展示的模块边界

| Pass | 主要输入 | 主要输出 | 可视化内容 |
| --- | --- | --- | --- |
| `tsc_inst_translator` | Qiskit 线路、翻译选项 | `sc_dag` | 线路图、逻辑指令 DAG、量子与经典依赖 |
| `plane_initializer` | 逻辑比特数、平面类型 | `plane_char` | M/Y 资源端口与 N 普通单元组成的网格 |
| `tsc_inst_scheduler` | 逻辑 DAG、平面、调度选项 | `inst_schedule_trace`、`req_schedule_trace` | 每一逻辑层的指令、资源请求及并行关系 |
| `sa_mapper` | 指令调度、平面 | `sa_mapping` | 交互关系、逻辑比特到物理单元的初始映射 |
| `tsc_uop_scheduler_comptime` | 平面、初始映射、两类指令 trace、硬件配置 | µop 调度、平面与寄存器快照 | 激光资源甘特图、层结束时的布局与真实 MOVE 分段路径 |

上游 `run_analysis_scripts.py` 将前四个模块组合为 `compilation_stage`，将第五个模块放在 `execution_stage` 中。本 Demo 将五个模块分别执行，便于观察它们的边界；µop 生成与调度属于上游的架构执行模拟阶段。

示例显式初始化输入比特，并使用 H、CX、T、S 和测量。T/S 翻译会请求 M/Y 资源并引入测量、条件 Pauli 操作及寄存器名称变化。图中的 `Q*`、`M*`、`Y*` 是 NAQsim 的寄存器名称；teleportation 后同一原始逻辑比特的当前名称可能变化。

逻辑指令 scheduler 会修改输入 DAG。Notebook 保留输入副本，再将独立副本交给 scheduler，保证输入图在后续单元格中仍然可查看。
同一逻辑层的事项会在执行阶段按子步骤展开，逻辑层图的横排不表示全部事项在同一物理时刻执行。条件 Pauli 保留为静态编译元数据，执行模型没有独立校正 µop。

## 图表和时间的含义

SA mapper 的每次 trial 都使用上游固定的 `random.Random(0)`。Demo 保留上游默认参数；其 `run()` 会重新初始化 SA 参数，不能通过运行前直接赋值来改变这些参数。首次执行的耗时可能包含可选 Numba JIT 编译。

µop schedule 的每条记录为 `(uop, interval_type, (begin_us, end_us))`。上游在进入每个逻辑层时将时间重新归零，因此单层甘特图横轴表示**该层内部时间**。跨层甘特图使用各层时长的累计偏移；不能将不同层的局部时间直接叠加解读为全局并行。

`plane_trace` 和 `qregs_trace` 保存的是**每个逻辑层结束时**的状态。布局图中的移动信息来自 MOVE µop 记录，不是逐时刻采样的连续原子轨迹，也不表示每条 µop 完成后都保存了一张平面快照。

本 Demo 的图表反映 NAQsim 的依赖、资源和时间模型。M/Y 端口与 N 网格是逻辑 patch 层面的架构表示；结果不包含量子态矢量模拟或实测硬件数据。

## 查看某一层和导出数据

运行 `inspect_layer(k)`，其中 `k` 是从 0 开始的逻辑层号，可以并列查看该层输入指令、开始位置、µop 区间、MOVE 路径和结束位置。`uop_df`、`instruction_df`、`qregs_df` 等变量保留完整结果。

最后的单元格将完整数据表导出到 `demo_outputs/`，包括线路、DAG 节点与边、指令层、初始映射、µop 区间、每层时延、寄存器快照及移动分段；`manifest.json` 记录解释器、配置、包版本、上游 commit 和所调用源码的 SHA-256。此目录是可再生成的输出，不纳入源码提交。

## 验证记录

2026-10-13 在注册的 `py311` 内核（Python 3.13.14）中从头执行：12 个代码单元格全部通过，生成 20 张图和 10 份 CSV。示例产生 9 个逻辑层，模型总时长为 4146.28 µs；完整性断言覆盖资源请求、ROT、MOVE、ESM 和 trace 对齐。DAG、逻辑层、映射、甘特图及空间快照均已检查可读性。实际依赖版本见 [环境记录](environment_py311.md)，与上游全量锁定版本不同；验证范围是本 demo。
