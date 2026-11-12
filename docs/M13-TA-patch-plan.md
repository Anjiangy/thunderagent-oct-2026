# 在 TA 本体上打补丁：让“暂停/恢复”从被动驱逐变成主动控制

方向（用户确认）：**始终以 ThunderAgent 为本体**，在它上面加两个开关 + 一个执行器，使 KV 的去留由我们的策略决定，而不是由 vLLM 的块级 LRU 被动淘汰。

## 一、为什么必须改 TA 本体

TA 现在的行为链条是：

1. 新 program 来了 → `_select_backend_for_new_program()` 只在 `remaining_capacity() >= tokens + BUFFER_PER_PROGRAM` 时才放行；
2. 放不下 → 排队 → `_wait_for_resume()`（`timeout=1800 s`）把请求挂住；
3. 容量不够时 `_pause_program()` 把 program 暂停：`backend.unregister_program()` 从 TA 账本移除、`origin_backend` 清空；
4. program 恢复时 `_resume_program()` 重新登记，**可能换到另一张卡**，此时那卡上没有它的 KV → 全量 prefill（这就是“被动驱逐”）。

也就是说：**TA 只会“记账 + 暂停/放行”，从不主动搬运或保活**；而它暂停 program 的那一刻，恰好让 vLLM 有机会把这块 KV 按 LRU 清掉。要让 KV 由我们控制，必须在 TA 里插两个口子：

## 二、已落地的补丁（`patches/ta_overcommit.py`，幂等，`router.py` 6 处标记）

**开关 A：`TA_OVERCOMMIT=1` —— 超容也放行**

- `_select_backend_for_new_program()`：原来放不下就 `continue`（返回 None → 排队 1800 s），现在放不下时改为按 `active_program_tokens` 最小者放行；
- 兜底：即便全都没有余量，只要 `healthy` 就选最空的一张，绝不让请求无限等。
- `update_program_before_request()` 里两处 `await self._wait_for_resume(...)` 用 `if not _ta_overcommit()` 包住 —— 不暂停就不会触发“卸载 → LRU 清块”。

**语义**：`TA_OVERCOMMIT=1` 时 TA 退化成“记账 + 负载均衡”，容量压力交给我们上层的驻留策略处理（这正是我们要的实验条件）。

**开关 B（下一步，已有锚点）：program → instance hint**

- 在 `update_program_before_request()` 入口读 body 里的 `program_id_hint`（取值 `a`/`b`，映射来自 `TA_HINT_BACKENDS="a=http://...,b=http://..."`）；
- 若该 program 当前所在卡与 hint 不一致且目标卡 healthy：`unregister_program(old)` → `register_program(new)` → 记 `migrations++`；
- 这样“搬不搬、搬到哪”由上游玩家决定，TA 只负责把账算对。

**执行器（第三步）**：hint 改变后，目标卡若没有这段前缀，由 executor 侧先 `capture+pull`（M6 已验证 1.82×）或 `recompute` 预热，再让 hint 生效——即“主动搬迁/激活”，而不是等 LRU 淘汰后重算。

## 三、验证与待办

已验证：`python -c "ast.parse(...)"` 通过（6 处标记）；`router.py.bak` 已备份。

待做（按顺序）：
1. **hint 接线**：读 TA `app.py` 的请求路径（`/v1/chat/completions` 里 `program_id` 的解析点），把 `program_id_hint` 传进 `update_program_before_request`；
2. **单测**：`tests/test_ta_overcommit.py`（纯逻辑：overcommit 关 → 无容量时不放行；开 → 放行并选最空；hint 一致时不迁移、不一致时迁移且计数）；
3. **真机 A/B**：同一 32-program 负载，三臂 = `TA 默认` / `TA + overcommit` / `TA + overcommit + hint(常量)`，看 paused 峰值、命中率、token/s；
4. **第四臂**：`hint 由 executor 的驻留信号驱动`（KV 在 A 就 hint=a），这才是“用策略控制 KV”的完整形态。

## 四、边界（先说清楚）

- 本补丁改的是**控制面语义**，不碰 vLLM 的块管理：它能让“不该被淘汰的 program 不再被 TA 暂停”，但**不能阻止 vLLM 因物理容量不足而 LRU 淘汰**。真正的“保活”仍需 1-token ping（M11 已验证 0/10→10/10）或迁移。
- `TA_OVERCOMMIT=1` 会让 vLLM 的 KV 使用率顶到 1.0 附近，请求可能排队 —— 这是有意为之：把“谁该被让位”的决策从 vLLM 的 LRU 换到我们的策略。
