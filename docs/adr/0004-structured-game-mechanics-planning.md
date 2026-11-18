# ADR-0004：基于状态不变量与可手算样例的游戏规则结构化规划

- **状态**：已采纳
- **关联模块**：`apps/api/atoms/runtime/orchestration.py`、`apps/api/atoms/runtime/prompts.py`、`apps/api/atoms/skills/game-mechanics*.md`

## 背景

浏览器小游戏（如 2048 滑块合并、横版平台跳跃、三消、塔防、3D 第一人称射击）在单次代码生成中最容易出现“界面画出来了，但核心规则错位”的问题——例如 2048 向右/向下合并写回方向反了、单回合重复合并同一数字块、或平台首跳高度超过了物理可达极值 `v² / (2g)` 导致玩家卡死在出生点。

## 决策

在 React 游戏项目的两阶段工作流中，要求主规划 Agent（Planner）在 `TaskPlan.mechanics`（`apps/api/atoms/runtime/orchestration.py`）中先输出受严格 Pydantic Schema 约束的**形式化玩法契约**，再交由生成 Agent 编码：

1. **动作-条件-有序副作用拆解**：
   - `initial_state` 明确开局棋盘/坐标/资源；
   - `actions` 将每次输入拆解为触发条件 `when` 与严格按序执行的 `effects` 列表；
   - `invariants` 声明不可违背的规则不变量（如“同一滑块单次移动最多合并一次”“仅用实际碰撞面判定落地”）。
2. **2～4 个确定性可手算样例（`mechanics.examples`）**：
   - 规划阶段必须给出具体的 `setup`、`action` 与随机生成前的确定性 `expected` 结果（如 `[2,2,0,0]` 向右得到 `[0,0,0,4]`、首跳起点到第一块平台顶面的落点）；
   - 生成阶段提示词要求模型先实现独立于 React 视图层的纯规则模块，按 `examples` 逐条核对执行路径与边界后，再接入 Canvas / Three.js / DOM 渲染与 HUD，并将 `src/agent/plan.json` 随版本持久化以便修复轮次继续对齐同一套规则。

## 后果

- **正面**：显著降低了方向颠倒、连锁结算死循环与不可达关卡等逻辑硬伤，且多轮自动修复时不会因重写而漂移原有玩法规则。
- **权衡**：规划阶段需要多生成约数百 Token 的结构化 `mechanics` JSON，故将规划输出预算控制在 `4096` Token 内并设置独立超时保证响应速度。
