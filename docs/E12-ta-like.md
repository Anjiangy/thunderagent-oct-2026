# E12 — mod 的 `ta_like` 模式：用我们的决策点跑 TA 的会计规则

目标：回答“TA + 自主搬迁能不能保证不劣于 TA”。结论先行：**能，但前提是搬迁动作必须落在路由决策点上**。`ta_like` 就是把这件事做实的实现。

## 规则（三条，按优先级）

1. **容量账本**（照抄 TA 的口径）
   `held(card) = Σ program_tokens(card) + BUFFER_PER_PROGRAM × count(card)`，`BUFFER_PER_PROGRAM = 100`；
   容量取自引擎 `vllm:cache_config_info`（`block_size × num_gpu_blocks`，本机 892×128 = 114,176）。
2. **先暂停，后搬迁**
   溢出量 `over = held + est − capacity`；
   若 `over / 800 tok/s ≤ 2 s` 且该卡有在飞请求 → **停等**（`asyncio.sleep`），不搬。
3. **只在目的地装得下时搬**
   搬的条件不是“另一张卡更空”，而是“另一张卡的剩余 ≥ 该 program 的前缀”；
   搬完立即把 `program → card` 写成路由事实（后续请求直接走新卡），不再当建议。

## 实现

- `mod/policy.py`：纯函数 `decide(cards, load, counts, capacity, in_flight, own, est, current) -> (card, hold_s, migrated)`，**不依赖 web 框架**，可直接单测。
- `mod/cli.py`：`--mode ta_like`、`--capacity a=114176 --capacity b=114176`；`/healthz` 新增 `capacity_tokens / in_flight / holds / hold_seconds_total / migrations`。
- `patches/add_ta_like.py`：幂等补丁（锚点缺失即 SystemExit，重复执行打印 already patched）。

## 验证

- 单测：`tests/test_ta_like.py` 6 个（容量恰好装下、短溢出停等、大溢出搬迁、全无空位时停等封顶、不往装不下的卡搬、buffer 计费）→ **全套 50 passed**。
- 真机（昇腾 31475，A=127.0.0.1:8110、B=<POD-M-POD>:8110，各 114,176）：
  - `/healthz`：`mode=ta_like, capacity {a:114176,b:114176}, in_flight {}, holds 0`；
  - 一次带 `program_id` 的 chat 请求 → `200`，随后 `programs_pinned 1`、`load_tokens {a:39,b:0}`、`in_flight {a:0}` → 计数闭环正确。

## 与旧模式的差别（为什么这才是“TA + 搬家”）

| 模式 | 谁决定放置 | 用容量账本 | 搬完是否影响路由 |
|---|---|---|---|
| affinity / sticky | 我们（按字节负载） | ❌ | ✅（但不知道容量，容易搬进快满的卡） |
| TA → 每卡 executor | TA | ✅（TA 的） | ❌（pin 被 TA 无视） |
| **ta_like** | 我们 | ✅（照抄 TA 公式） | ✅（搬完即路由事实） |

## 还没做的

- 未跑 32 program 的 A/B（需要 18104 隧道 + 两臂各一次，约 20 分钟）。
- 停等用的是固定 800 tok/s 的排空估计，真实值应按 `/metrics` 的 `generation_tokens_total` 差分自适应。
- 没有把“暂停中的 program 集合”暴露给客户端（TA 有 `/programs`），目前只有计数。
