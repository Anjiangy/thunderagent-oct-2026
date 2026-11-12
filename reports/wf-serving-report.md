# vLLM Workflow-Aware Serving 仓库深度分析报告

> 分析对象：`intellistream/vllm-workflow-aware-serving`（私有仓库，本地 clone 于 `E:\studyfiles\dsh\Thunderagent\vllm-workflow-aware-serving`）
> 分析方式：源码精读 + vLLM fork submodule 交叉验证；基于 git 提交 e4ce3364（分支 main）

---

## 一、分析对象与前提说明（含仓库可达性结论）

### 1.1 可达性结论
- `https://github.com/intellistream/vllm-workflow-aware-serving` **直接访问返回 404**——因为它是**私有仓库**。
- 通过本机 `gh` CLI（账号 `Anjiangy`，OAuth keyring 认证）成功 `gh repo view` 与 `git clone`。
- **结论：以本仓库为主分析对象**（不 fallback 到 RIDE-Lab/SAGE）。

### 1.2 生态归属

| 名称 | 定位 | 关系 |
|---|---|---|
| `intellistream/vllm-workflow-aware-serving` | 请求控制面 + 工作负载 + KV 迁移原型 | 主分析对象 |
| `vLLM-HUST/vllm-hust`（submodule） | vLLM fork：Ascend/NPU 使能 + dev 控制端点 | 被调度的推理引擎 |
| RIDE-Lab/SAGE | Streaming-Augmented Generative Execution | 生态对照 |
| SAGA（arXiv:2605.00528） | Workflow-Atomic Scheduling | 概念锚点 |
| ThunderAgent（arXiv:2602.13692） | Agent 程序容量限流 | **调度机制直接来源** |

### 1.3 仓库定位
**独立 request control plane（scheduler 层），不是 vLLM fork / extension。**
- `pyproject.toml`：发行名 `vllm-hust-request-control-plane`，import `request_control_plane`；`dependencies = []`（纯标准库）；`requires-python >= 3.11`；作者 Yancan Mao；Apache-2.0；可选 `ray[default]>=2.40` / `dev` / `viz`。
- 耦合边界：控制面与 vLLM 唯一交互面 = **HTTP + `/metrics`**（转发 OpenAI 兼容端点 + 抓 Prometheus 指标反推 KV 容量）。vLLM 内部改动在 submodule fork 里，且主要是 **Ascend 使能 + dev 端点**，**不含** program/workflow 级 KV 逻辑。

---

## 二、一页纸架构图（ASCII）

```
                         +-------------------------------------------------+
   agent / 客户端 -------->|  请求控制面 request_control_plane (stdlib)      |
  (OpenAI 兼容 +         |                                                 |
   program_id 标注)       |  runtime/router.py  -> Router (HTTP 前端+决策)  |
                         |    |  policy="program" 时开限流                 |
                         |    v                                            |
                         |  controller/program_controller.py               |
                         |    -> ProgramController(RequestController)       |
                         |       decide() -> Route/Hold/Reject              |
                         |       +-> program_throttling.py (容量账本+暂停)   |
                         |       +-> routing_policies.py (least_load/session)|
                         |    |                                            |
                         |  metrics/metrics_collector.py  <- /metrics       |
                         |  actuator/vllm_actuator.py -> VllmActuator.route |
                         +---------------------------+---------------------+
                                                     | HTTP
                         +---------------------------v---------------------+
                         |  vLLM fork third_party/vllm-hust (submodule)    |
                         |   标准 PagedAttention / BlockPool / prefix cache  |
                         |   (ref_cnt, free_blocks)                         |
                         |   dev 端点: /sleep /wake_up /pause /resume        |
                         |             /reset_prefix_cache /abort_requests   |
                         |   指标: vllm:engine_sleep_state, cache_config     |
                         +-------------------------------------------------+

   离线/研究层（不进线上调度循环）:
   +------------------------------------------------------+
   | emulation/workflow_emulation/  (CPU-only DAG 仿真)    |
   |   contract/vocabulary.py -> Node/Workflow/DagClass    |
   |   contract/critical_path.py -> R_v (关键路径)          |
   |   replay/discrete_event_replay.py -> FCFS/SJF/CP/ATLAS |
   +------------------------------------------------------+
   | experiments/kv_adaptation/  (KV 迁移原型, 未接入主控)  |
   |   program_references.py -> program 级 KV 引用          |
   |   transfer.py -> 跨节点迁移事务 (只发命令)              |
   |   store_connector.py -> AscendStore 测量包装           |
   +------------------------------------------------------+
```

---

## 三、端到端路径追踪

| # | 阶段 | 关键文件/类 | workflow-aware 增量 |
|---|---|---|---|
| 1 | 接入 | `runtime/router.py` `Router` | 解析 `program_id`（顶层或 `vllm_xargs.program_id`），把逐 request 归类为多轮 program |
| 2 | 决策 | `controller/program_controller.py` `ProgramController.decide()` | 有 program_id → `ProgramThrottling.on_request()`；无 → 普通 `RequestController` |
| 3 | 容量判定 | `controller/program_throttling.py` `ProgramThrottling` | `used = Σ(context_tokens + 100)` vs `kv_capacity_tokens = block_size × num_gpu_blocks` |
| 4 | 亲和路由 | `state/program_state.py` `ProgramState.instance_id` + `routing_policies.py` | 同 program 固定打同实例，后续轮复用 KV |
| 5 | 执行 | `actuator/vllm_actuator.py` `VllmActuator.route()` / `HttpRouteHandle` | HTTP 转发；流式首字节=控制面 TTFT |
| 6 | KV 复用 | fork 原生 prefix cache + `experiments/kv_adaptation/program_references.py` | 亲和复用；主动保留 `pool.touch()` 提 `ref_cnt` 防逐 |
| 7 | 结果反馈 | `metrics/metrics_collector.py` `MetricsCollector.collect()` | 抓 `/metrics` 更新 `kv_usage`/`ttft`/`foreign_load` |
| 8 | 返回+释放 | `program_controller.py` `on_result()` / `release()` | program 结束交回容量账本 |

**关键观察**：真正 workflow-aware 的增量在 **第 1/3/4 步（program 抽象 + 容量限流 + 亲和）**；KV 保留/迁移在 `experiments/kv_adaptation` 原型，**未接入主调度循环**。

---

## 四、核心机制拆解

### 4.1 Program 抽象
`state/program_state.py`：`ProgramPhase`(REASONING/ACTING)、`ProgramLifecycle`(ACTIVE/PAUSED/RELEASED)、`ProgramState`(program_id/phase/lifecycle/instance_id/context_tokens/steps/calls_in_flight/marked_for_pause; `is_new = steps <= 1`)。`RequestState.program_id` 来自顶层或 `vllm_xargs.program_id`。

### 4.2 容量限流（ThunderAgent 再实现）
`controller/program_throttling.py` `ProgramThrottling`：
- 容量 `kv_capacity_tokens = block_size × num_gpu_blocks`（`/metrics` 的 `vllm:cache_config_info`）。
- 占用 `used = Σ(context_tokens + BUFFER_PER_PROGRAM=100)`；`context_tokens` 用 `CHARS_PER_TOKEN_DEFAULT=3.6` 估算、有 usage 后修正。
- 决策：新 program 放占用最少且有空间的引擎（仅当无人等待）；暂停 program 下次调用 `HoldDecision`（`pause_timeout_s=1800` 后 503）；每 `tick=1s`（上游 5s）贪心恢复 `REASONING > 新 > ACTING`，BFD 放置；超容量先暂停最小 ACTING。

### 4.3 Session-affinity
- program 级：`ProgramState.instance_id` 固定，后续轮复用 KV。
- request 级：`routing_policies.py` `session` = `sha1(session_id) % N`，`router.py` `--session-key`（默认 `x-session-id`）。
- 与 continuous batching 交互：控制面只做跨引擎路由+准入，引擎内部 batching 交给 vLLM；`foreign_load = engine(running+waiting) - inflight` 区分外负载。**无 work stealing**。

### 4.4 Workflow 表示（离线仿真层）
`emulation/workflow_emulation/`（CPU-only，不参与线上调度）：
- `contract/vocabulary.py`：`NodeKind`(LLM/TOOL)、`DagClass`(SINGLE/CHAIN/FORK_JOIN/TOOL_PAUSE/ROLLBACK/SHARED_STATE)、`DisclosureMode`(FULL/PROGRESSIVE)、`NodeStatus`、`EventType`、`LEGAL_TRANSITIONS`；`Node` 含 `service_ground_truth` 与 `service_estimate`（分离=反泄漏）。
- `contract/critical_path.py`：`critical_path_length`(L_w)、`remaining_critical_path`(R_v)、`topological_order`(Kahn)。
- **线上控制面携带 `workflow_id/node_id/R_v` 仅作元数据，不参与调度**；按 R_v 调度在 `replay/discrete_event_replay.py` 离线对比 FCFS/SJF/ATLAS。

### 4.5 KV cache workflow 感知
无 WA-LRU/TTL/prefetch 新算法。两层：
- (a) 线上隐式：program 亲和 + 原生 prefix cache。
- (b) 原型显式：`experiments/kv_adaptation/program_references.py` `ProgramReferences`(retain/release/status/expire) 复用原生 `BlockPool.touch()/free_blocks()`（`max_blocks=24`、`ttl=300`），不改 eviction。
- 配套：`planner.py`(canary 门 BLOCKED/ELIGIBLE_FOR_CANARY)、`transfer.py`(TransferController, REASONING/TOOL_WAIT/READY/FINISHED, 只发 Command)、`store_connector.py`(MeasuredAscendStoreConnector)、`cross_node_mechanism.py`(2 节点 Ray)。

---

## 五、可复现性评估与最小实验路径

### 5.1 清单
| 目录 | 内容 | 随仓库 |
|---|---|---|
| `experiments/workload/` | 负载生成/回放/采样/分析（`generate_workload.py`/`replay_requests.py`/`build_program_workload.py`/`arrival_process.py` + plot_*） | 是 |
| `experiments/control_plane/` | `workflow_load_generator.py`、`agent_program_metrics.py`(`summarise()`)、`mock_engines_demo.py`、`ray_benchmark.py`、`thunderagent_router.py` | 是 |
| `experiments/emulation/` | `run.py`/`policy_matrix.py`/`load_sweep.py` | 是 |
| `experiments/kv_adaptation/` | 迁移/引用/交接探针 | 是 |
| `emulation/workflow_emulation/` | trace 生成 + 离散回放 + 校验 | 是 |
| 外部轨迹源 | SWE-smith（`scripts/prepare_agent_trajectories.py`） | **否** |

### 5.2 依赖
控制面 stdlib-only 可独立跑；引擎 = fork `e4ce3364`（Ascend 特性需对应硬件，普通 GPU 上标准 vLLM 即可被调度）；跨节点 KV 需 `ray>=2.40`。

### 5.3 具体阻塞项
1. workload 首步依赖外部 SWE-smith 轨迹（不随附）。
2. dev 端点需 `VLLM_SERVER_DEV_MODE=1`，否则 `/pause /resume /sleep /wake_up /reset_prefix_cache` 404。
3. kv_adaptation 依赖 AscendStore/Mooncake，README 记录 **Mooncake 退出错误未解**，纯 NVIDIA 单卡跑不通。
4. ray_benchmark / cross_node_mechanism 需 ≥2 节点。

### 5.4 最小路径
- **A（CPU-only）**：`emulation/workflow_emulation` → `generate` 生成 DAG trace → `replay --policy critical-path-online-estimate`，对比 FCFS/SJF/ATLAS。
- **B（单卡）**：`testing/mock_vllm_server.py` 起 mock 引擎 → `python -m request_control_plane --endpoint ... --policy program` → `workflow_load_generator.py` 打负载 → `agent_program_metrics.py` 汇总。卡点：mock 是否发 `cache_config_info`/`engine_sleep_state` 指标。

---

## 六、批判性判断

1. **成熟度两极**：控制面干净（stdlib-only、`@dataclass`+`StrEnum`、设计文档完整），但**无 CI 配置、无依赖锁**；`kv_adaptation` 是研究原型——自述"两节点交接已跑、Mooncake 退出错误未解、未接入主控、未证明整体提速"。
2. **真实 delta 很小**：fork `vllm/v1/core/` grep `program_id|program_ref|workflow` 零命中，只有标准 `ref_cnt`/`free_blocks` + dev 端点 + `vllm:engine_sleep_state`（`vllm/v1/metrics/loggers.py:507-524`）。去掉 workflow-aware 部分 = 标准 vLLM + HTTP 反代路由器。
3. **契约漂移（可验证）**：控制面 `metrics_collector.py` 解析 `vllm:preemption_policy_enabled`，但 pinned fork e4ce3364 里 grep `preemption_policy` **零命中**（只 emit `engine_sleep_state`）——指标来自另一版本/分支，或控制面先于 fork 落地。
4. **workflow-aware 调度未上线**：线上是 program 粒度限流+亲和（ThunderAgent 路线），非 SAGA 式 AEG/Distributed Scheduler；DAG 关键路径调度只在 `emulation/` 离线仿真，控制面的 `workflow_id/node_id/R_v` 明确"仅元数据不参与调度"。
5. **可迁移性**：最值得抄 = `program_references.py`（不改引擎实现 program 级 KV 引用，最小可行样板）；最不值得抄 = `transfer.py`（纯命令式 CPU 原型、依赖未解的 Mooncake/AscendStore，成本收益未实测）。

---

## 七、下一步深入 3 建议

1. 精读 `program_throttling.py` `tick()/used()/free()`，验证 `BUFFER_PER_PROGRAM=100` 与 `CHARS_PER_TOKEN_DEFAULT=3.6` 对容量账本的影响。
2. 跑 `discrete_event_replay.py`，对比 `CRITICAL_PATH_ORACLE`(ground_truth) vs `CRITICAL_PATH_ONLINE`(estimate) 的 makespan 差距。
3. 对照 fork `vllm/v1/core/sched/scheduler.py` 与 `block_pool.py`，确认 `touch()/free_blocks()` 语义（`ref_cnt` 归零、`delay_free_blocks` 异步）以判断 kv_adaptation 能否无损移植标准 vLLM。
