# 启发式编译器 — 核心思想与伪代码

基于 `heuristic.py`。与 MVQC 不同：不在每个 CZ stage 内做固定「拉拽 + 腾位」流水线，而是**按块维护 CZ pool**，在 pool 上**贪心重排**，直到部分门满足连接性后批量执行。

## 芯片与连接性

- **纠缠区**：`0 ≤ x, y < row`；**存储区**：`y < 0`（可选 `storage_flag`）。
- **连接性**：两 qubit 位于**同一格点**即可执行 CZ（与 MVQC 拉拽模型一致）。
- **AOD stage**：同一 stage 内移动须满足 x/y 方向无冲突（复用 `mvqc.check_conflict`）；stage 耗时 = 该 stage 内最长单原子移动时间。

## 主循环

```
heuristic_compile(cz_blocks, row, n, storage_flag):
    初始化布局 pos（SA 或给定 mapping）
    block_idx ← 0
    cz_pool ← cz_blocks[0]

    while cz_pool 非空 或 还有未处理的 block:
        if cz_pool 为空:
            block_idx += 1；cz_pool ← 下一 block；continue

        # 1. 重排一轮
        state ← RearrangeState(pos, used=∅, cz_pool)
        state, aod_stages, t_move ← rearrange_round(state)
        pos ← state.pos
        记录 timeline: rearrange

        # 2. 执行已就绪的 CZ
        ready ← { g ∈ cz_pool | pos[g₀] == pos[g₁] }
        if ready 为空: stagnant += 1；若超限则报错
        while ready 非空:
            batch ← ready 中极大无共享 qubit 子集（贪心）
            执行 batch 中所有 CZ；从 cz_pool 移除
            ready ← 更新后的就绪门集合
            记录 timeline: cz
```

**块策略**：当前 block 的 gate 全部执行完后，才将下一 block 的门并入 `cz_pool`。重排始终只针对 pool 内的门。

## 重排轮（贪心）

每轮从空 `used` 开始，反复选**单位时间回报密度**最大的动作，直到无合法候选：

```
rearrange_round(state):
    while 存在候选 且 步数 < MAX_REARRANGE_STEPS:
        candidates ← generate_candidates(state)

        for each action in candidates:
            模拟执行 action，更新 pos 与 aod_queue
            reward ← 空间收益 + split/load/store 额外收益
            time   ← aod_queue 总时间（新移动按最小增量插入 stage）
            density ← max(total_reward/time, action_reward/Δtime)

        选取 density 最大的 action，提交到 state
        pull/load/store 将涉及 qubit 加入 used；split 不标记

    返回本 round 新增的 AOD stages
```

**`used` 语义**：防止同一轮内重复操作同一 qubit。Pull 还会把门两端都标为 used。

## 四类候选动作

| 动作 | 含义 | 触发条件（简述） |
|------|------|------------------|
| **Pull** | 将一端拉到 partner 所在格 | pool 内门对；目标格仅 partner 独占 |
| **Load** | memory → 纠缠区最近空位 | partner 在 memory；无等价 pull 时 |
| **Split** | 同格非 pool 对拆开 | 纠缠区共址且该对不在 pool |
| **Store** | 纠缠区 → memory 最近空位 | 开启 storage；pool 内所有 partner 均已 used |

```
generate_candidates(state):
    for (q₀, q₁) in cz_pool:
        Pull:  q_pull → pos[q_stay]（单向，目标格最多只有 q_stay）
        Load:  q ∈ {q₀,q₁} 在 memory → 最近纠缠区空位

    for 纠缠区同格对 (q₀, q₁) 且 (q₀,q₁) ∉ pool:
        Split: 任选一方 → 最近纠缠区空位（排除原格）

    if storage_flag:
        for q 在纠缠区 且 pool 内 partner 均已 used:
            Store: q → 最近 memory 空位

    过滤：used qubit 不得出现在候选中
```

## 回报模型

```
空间代价 C(pool, pos) = Σ_{g∈pool}  -G / (dist(pos[g₀], pos[g₁]) + 1)

单步 action_reward =
    C(before) - C(after)     # 拉近 pool 内门对 → 正值
  + R_split  × 拆开的非 pool 同格对数
  + R_load   × memory→纠缠区的 load 数
  + R_store  × 纠缠区→memory 的 store 数
```

**核心思想**：用**可执行的局部移动**（pull/split/load/store）降低 pool 内门的空间代价；密度贪心在「多拉近一对门」与「少花时间」之间折中。Split 清理历史叠位；Store 在 partner 已处理完后腾出纠缠区。

## 与 MVQC 的对比（直觉）

| | MVQC | 本启发式 |
|---|------|----------|
| 调度单位 | 固定 CZ stage（整块门列表） | 可变长重排 + 就绪即执行 |
| 移动策略 | 每 stage 规则化 pull + redundant | 四类动作 + 回报密度贪心 |
| pool | 无（逐 stage 弹出） | 按 block 累积，执行后删减 |

## 入口

- 编译：`heuristic_compile(...)` / `python run.py`
- 输出：`trace.json`（`rearrange` + `cz` 时间线），可用 `visualize.py` 生成动画
