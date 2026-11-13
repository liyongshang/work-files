# 实验入口

从项目根目录运行，先执行 `python -m pip install -e ".[test,notebook]"`。

```bash
python experiments/run_random.py --config experiments/configs/random_smoke.json
python experiments/run_feynman.py --config experiments/configs/feynman.json
python experiments/rerun_timeout.py --prior outputs/archive/results_feynman_algorithms/results.json
```

参数优先级：命令行 > JSON 配置 > 默认值。配置字段使用 argparse 参数名，如 `window_size`。

新运行默认写入 `outputs/runs/<时间>_<实验名>/`，保存 config.json、metadata.json、输入哈希、源码哈希、Python 与依赖版本。没有 Git 仓库时 git_revision 为 null，以源码哈希区分版本。随机实验另存 attempts.jsonl，包含成功、超时与生成失败；成功样本仍按既有算法继续采样，分析时应同时报告失败样本，避免选择偏差。

Feynman 与补跑脚本允许使用相同 `--output` 恢复断点，但配置、输入哈希和源码哈希必须一致。随机实验不覆盖已有目录。历史输出缺少可靠运行元数据，不能直接作为新运行的断点；补跑需通过 `--prior` 关联原始结果。

`archive/` 保存一次性历史性能对比与原始基线代码，不属于日常基准入口。
