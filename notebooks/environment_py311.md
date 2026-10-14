# py311 环境记录

2026-10-13 按用户确认，将现有 conda 环境 `py311` 从 Python 3.12.13 升级到 **Python 3.13.14**。
环境名与 Jupyter 内核名均保留为 `py311`，显示名为 `Python (py311)`。

解释器：`C:\Users\lys\.conda\envs\py311\python.exe`。

本次只迁移 demo 所需包；以下包按原版本重装对应 Python 3.13 wheel：

`numpy`、`pandas`、`scipy`、`matplotlib`、`contourpy`、`kiwisolver`、`fonttools`、`pillow`、`rpds-py`、`symengine`、`numba`。

Conda 同时更新 Python 与其管理的内核及基础运行依赖。更新前版本清单和安装记录保存在父项目 `outputs/naqsim_demo/`。

## Demo 的实际包版本

| 包 | 版本 |
| --- | --- |
| `qiskit` | 1.2.4 |
| `numpy` | 2.1.2 |
| `pandas` | 2.2.3 |
| `scipy` | 1.14.1 |
| `rustworkx` | 0.18.0 |
| `matplotlib` | 3.9.2 |
| `ipykernel` | 7.3.0 |
| `nbformat` | 5.10.4 |
| `jupyter-client` | 8.10.0 |
| `numba` | 0.67.0 |
| `llvmlite` | 0.49.0 |
| `rpds-py` | 2026.5.1 |
| `symengine` | 0.13.0 |
| `contourpy` | 1.3.3 |
| `kiwisolver` | 1.5.0 |
| `fonttools` | 4.62.1 |
| `pillow` | 12.2.0 |

## 按确认暂未迁移的 Python 3.12 二进制包

以下包仍包含 CPython 3.12 专用扩展文件或 wheel 标签，在 Python 3.13 下需要单独迁移。本次没有修改它们，也没有验证这些包的功能；不要将 demo 成功视为整个原环境都已兼容。

| 包 | 原版本 | 剩余 3.12 扩展文件示例 |
| --- | --- | --- |
| `cftime` | `1.6.5` | `cftime/_cftime.cp312-win_amd64.pyd` |
| `MarkupSafe` | `3.0.3` | `markupsafe/_speedups.cp312-win_amd64.pyd` |
| `pydantic_core` | `2.27.2` | `pydantic_core/_pydantic_core.cp312-win_amd64.pyd` |
| `python-sat` | `1.9.dev2` | `pycard.cp312-win_amd64.pyd` |
| `PyYAML` | `6.0.3` | `yaml/_yaml.cp312-win_amd64.pyd` |
| `stim` | `1.16.0` | `stim/_detect_machine_architecture.cp312-win_amd64.pyd` |
| `torch` | `2.13.0+cpu` | `torch/_C.cp312-win_amd64.pyd` |

如后续使用这些包的本地扩展，需根据其 Python 3.13 支持情况重新安装；Torch CPU 版本需保留原来源与构建要求后再决定迁移方式。MarkupSafe 和 PyYAML 可能使用纯 Python 回退；本表不代表整个包的每项功能都不可用。

进一步核对显示，`mqt-core` 与 MQT 开发版 `mqt.qmap` 使用 `cp312-abi3` wheel，而非 `cp312-cp312` 专用扩展。它们不属于上表，也没有被重装；本次未验证其功能。`netCDF4`、`igraph`、`psutil` 和保留的 Qiskit 也使用 abi3 wheel。
