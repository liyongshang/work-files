# 基准输入

`feynman_clifford/` 保存转换后的静态 Clifford QASM 和转换 manifest；`feynman_clifford_stats.json` 为线路统计。它们是实验输入，不是运行输出。

```bash
python tools/convert_feynman_clifford.py --seed 20260826
python tools/analyze_clifford_benchmarks.py
```

已有输入在本次整理中保留原路径和内容。实验结果统一写入 `outputs/runs/`，历史结果见 `outputs/archive/`。
