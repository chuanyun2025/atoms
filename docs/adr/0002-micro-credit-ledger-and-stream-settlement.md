# ADR-0002：微积分预授权账本、取消原子边界与流式断流用量保全

- **状态**：已采纳
- **关联模块**：`apps/api/atoms/billing/credits.py`、`apps/api/atoms/runtime/worker.py`、`apps/api/atoms/gateway/chat_completions.py`

## 背景

AI 生成任务耗时长、输出 Token 跨度大，且随时面临用户点击停止、异步协程取消（`CancelledError`）、上游 SSE 流中途断开或返回畸形 JSON 等异常边界。若直接事后扣费容易导致并发超支；若一遇异常就简单回滚或丢弃上下文，则会吞掉上游已真实消耗的算力账单，或把尚未发出的请求误标为“待核对（`uncertain`）”长期冻结用户余额。

## 决策

1. **百万分之一积分整数记账**：
   - 账本内部统一使用整数微单位（`1 credit = 1,000,000 units`，`apps/api/atoms/billing/credits.py`），按供应商真实返回的 `prompt_tokens` 与 `completion_tokens` 精确结算，彻底消除浮点舍入误差与整积分向上取整损耗。
2. **三阶段调用状态机（`dispatch_pending` 区分未发出与未知结果）**：
   - `reserve_call`：调用前按输入上界与输出预算冻结预授权（`status='in_flight', dispatch_pending=1`）；
   - `start_call`：紧邻发起模型请求前在主协程**同步**校验运行租约并将 `dispatch_pending` 置为 `0`，随后无等待点直接进入 `try ... except asyncio.CancelledError` 保护块（`apps/api/atoms/runtime/worker.py`）。若在派发前取消或停止，持有 `dispatch_pending=1` 的记录会立即全额释放（`released`）；仅当请求已实际派发且未拿到可信用量时，才转入 `uncertain` 冻结待人工核对（`ops.py credits-reconcile`）。
   - `settle_call`：收到合法 `usage` 后在同一写事务中扣减实耗、释放多余预授权并写入幂等流水；若上游返回异常超额 `usage`，挂起为 `USAGE_EXCEEDS_AUTHORIZATION` 防止扣出负余额。
3. **网关流式与畸形响应的已知用量保全**：
   - 内网 `provider-gateway` 默认启用 SSE 流式读取（`stream_options.include_usage=true`）以消除长生成首包空闲超时；
   - 在 `chat_completions.py` 中先提取并缓存有效 `usage`，即便后续分片出现 `choices` 为空、`message: null` 类型错误、流读取超时（`ReadTimeout`）或断流（`ReadError`），仍将已获得的 `usage` 随错误对象一并返回并标记 `uncertain=False`，由 Worker 按真实消耗完成结算。

## 后果

- **正面**：并发任务绝不超支，正常取消不误冻积分，上游半途报错但已给出 `usage` 的请求也能自动结清，账实严格一致。
- **权衡**：极少数上游既已扣费又彻底断网未回传 `usage` 的调用会保留在 `uncertain` 状态，需依赖运维命令对照上游账单做最终核销。
