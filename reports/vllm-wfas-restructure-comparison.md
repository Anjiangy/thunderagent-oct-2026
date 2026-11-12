# vllm-workflow-aware-serving：`feature-control-plane-restructure` 与 `intellistream/vllm-workflow-aware-serving` 对比分析

> 对照对象：旧版 = `E:\studyfiles\dsh\Thunderagent\vllm-workflow-aware-serving`（intellistream 主仓库 `main`，本会话早前已做深度解剖）；新版 = `E:\studyfiles\代码\vllm-workflow-aware-serving-feature-control-plane-restructure`（无 `.git` 的快照目录，用户指认为"后来的版本"）。

## 一、结论速览

这次 restructure 不是一次"整理目录"，而是一次**把 workflow-aware 研究从"在线控制面"里抽出去、只保留一个干净的最小请求路由器的范围收缩**。三条硬结论：

1. **program 级调度被整体删除**：旧版 `src/request_control_plane/` 里的 `controller/program_controller.py`、`controller/program_throttling.py`、`state/program_state.py` 三个文件在新版里**全部消失**。全仓库 grep `program_id|ProgramThrottling|ProgramController|throttl` 只剩 `test1.ipynb` 里一条绘图标签（残留物），代码里零匹配。
2. **workflow-aware 的重心从"在线 program 调度"搬到"离线模拟器"**：`emulation/workflow_emulation/` 两个版本**结构完全一致**（`contract/generation/replay/serialization/validation` 五子包），说明 DAG 轨迹 + 关键路径回放这条研究线被保留；被砍掉的是"在真实 vLLM 前做 program 容量限流 + 暂停/恢复"这条在线线。
3. **新版把控制面打磨成可打包、可 Ray 托管的纯请求路由器**：stdlib-only、wheel 发行、`RouterService` Ray actor、响应头、运行时切策略——这些是旧版 `main` 没有的工程化增量。

---

## 二、结构级 diff

### `src/request_control_plane/`（核心差异）

| 子目录 | 旧版（main） | 新版（restructure） |
|---|---|---|
| `controller/` | `controller_loop.py` · `request_controller.py` · `routing_policies.py` · **`program_controller.py`** · **`program_throttling.py`** | 仅前三者，program 两件删除 |
| `state/` | `decision.py` · `instance_state.py` · `request_state.py` · **`program_state.py`** | 仅前三者，program_state 删除 |
| `metrics/` · `actuator/` · `runtime/` · `testing/` | 相同 | 相同（`runtime/` 多出 `router_service.py`/`router_client.py` 的打磨） |

> 旧版 `runtime/` 其实已有 `router_service.py`/`router_client.py`，所以"Ray 托管"不是 restructure 新增，是旧版 `main` 已带、新版继续打磨。

### `experiments/`（大幅裁剪）

| 旧版 | 新版 | 变化 |
|---|---|---|
| `control_plane/`（含 `agent_program_benchmark.py`、`agent_program_metrics.py`、`thunderagent_router.py`、`thunderagent_log_series.py`、`workflow_load_generator.py`、`swebench/` 等 20+ 文件） | `control_plane/`（仅 `device_partition_probe.py`、`mock_fleet_demo.py`、`ray_benchmark.py`、`ray_cluster_app.py`、`router_query.py`） | **agent_program / thunderagent / swebench / 负载生成器全删** |
| `emulation/`（analysis/applicability/common/figures/load_sweep/policy_matrix/run） | `emulation/`（同名同文件） | 不变 |
| **`kv_adaptation/`（20 文件：planner/transfer/store_connector/program_references/handoff_connector 等）** | 无 | **KV 迁移原型整体删除** |
| **`workload/`（40+ 文件：arrival_process/replay_sessions/…）** | 无 | **删除** |
| **`sim/return_trend/`** | 无 | **删除** |

### `emulation/workflow_emulation/`

**两版本完全一致**：`contract/{critical_path,vocabulary}` · `generation/{trace_generator,workload_catalogue}` · `replay/discrete_event_replay` · `serialization/canonical_json` · `validation/trace_validator` · `command_line.py`。这条线是 restructure 里唯一被"原样保留"的研究资产。

### 顶层新增物

新版多出 `CHANGELOG.md`、`CONTRIBUTING.md`、`results/`、`test1.ipynb`、`tree_output.txt`、`.idea/`。其中 `test1.ipynb`（第 98 行含 "ThunderAgent (affinity + throttling)" 标签）是本地残留的实验/绘图笔记本，不属于控制面代码。

---

## 三、代码级 diff（关键行为差异）

### 3.1 路由入口：program 策略消失

- **旧版** `runtime/router.py`：`Router(..., policy="program")` 走 `PROGRAM_POLICY` → `ProgramController` 开 program 容量限流；否则走普通路由策略。
- **新版** `runtime/router.py`（L232）：`--policy choices=sorted(POLICIES)`，`POLICIES` 只含 `least_load / least_latency / round_robin / session`，**没有 `program`**。`Router.__init__` 直接实例化 `RequestController`（L47-55），不再有 program 分支。

### 3.2 控制器：从"program 容量限流"回到"请求路由"

- **旧版**：`ProgramController(RequestController)` + `ProgramThrottling`（`BUFFER_PER_PROGRAM=100`、`CHARS_PER_TOKEN_DEFAULT=3.6`、used=Σ(context_tokens+100) vs `kv_capacity_tokens`、tick 每 1s BFD resume、REASONING>new>ACTING、超容量暂停最小 ACTING）。
- **新版** `controller/request_controller.py`：`RequestController.decide()`（L74-92）只做三件事——`alive()` 过滤 → 无健康实例则 hold-then-reject（`hold_timeout_s=2.0` → 503）→ `POLICIES[policy]()` 选目标。`workflow_id / node_id / R_v` 只在 L89-91 作为 **reason 元数据**从 `request.xargs` 抄出来，**不参与任何调度决策**。

### 3.3 状态模型：program 状态机消失

- **旧版** `state/program_state.py`：`ProgramPhase`（REASONING/ACTING）、`ProgramLifecycle`（ACTIVE/PAUSED/RELEASED）、`ProgramState`（program_id/instance_id 亲和/context_tokens）。
- **新版** `state/`：只剩 `decision.py`（RouteDecision/HoldDecision/RejectDecision/ActionResult）、`instance_state.py`（含 `foreign_load`）、`request_state.py`（`xargs` 仍保留，供 workflow_id/node_id/R_v 元数据读取）。

### 3.4 新增的工程化增量（旧版 main 没有或未打磨的）

- **响应头**：`X-Control-Plane-Target / -Decision / -Request-Id`（`router.py` L197-199）；router 自生成 id `router-<n>`。
- **运行时可观察/可控制端点**：`/state`、`/stats`、`/recent?n=`、`/policy`（POST 运行时切策略）。
- **`RouterService`（Ray 可托管）**：README 明确 `runtime/` 下 `Router`（HTTP 前端）+ `RouterService`（Ray-hostable）；`ray_cluster_app.py` 把整栈作为一个 Ray job 提交（job-scoped actor，`ray job stop` 能释放设备）。
- **打包**：`make build` 产出 `vllm-hust-request-control-plane` wheel（`CHANGELOG` 顶部三条：wheel 打包、`RouterClient` 跨 Ray job 共享、舰队 teardown 不残留 EngineCore）。

---

## 四、"workflow-aware" 语义的迁移

| | 旧版 | 新版 |
|---|---|---|
| 在线调度单元 | program（program_id 锚点、容量限流、tool 边界暂停/恢复） | request（只有 workflow_id/node_id/R_v 当元数据） |
| workflow 知识来源 | 控制面内建的 program 状态机 | `vllm_xargs` 透传的 DAG 元数据 + 独立模拟器 |
| 调度策略研究 | 在线 program 限流 + KV 迁移原型 | 模拟器回放 FCFS/SJF/ATLAS/critical-path-oracle |
| 参照物 | ThunderAgent 是对照基线及调度机制来源 | 不引用 ThunderAgent，重锚到 vllm-hust#191（Agent DAG readiness） |

新版 README 一句话把新定位说清：控制面是"observe → decide → actuate → on_result"的纯请求路由器，"Policies: least_load, least_latency, round_robin, session. No Kubernetes, no vLLM changes"；而 workflow-aware 的实质内容（DAG 轨迹、关键路径 R_v、暂停/恢复、fork/join、shared state）被放到 `emulation/workflow_emulation/`，由"replay 结果选择或否决一个 M1 候选"来推进。

---

## 五、迁移与取舍（gained / lost）

**被移除（lost）**
1. `ProgramController` / `ProgramThrottling` / `ProgramState`——ThunderAgent 式 program 容量限流，从在线控制面消失。
2. `experiments/kv_adaptation/`——Mooncake/AscendStore KV 活迁移原型（planner/transfer/store_connector/program_references/handoff_connector）整体删除。
3. `experiments/workload/`（40+ 文件负载生成/回放）与 `experiments/sim/`。
4. `experiments/control_plane/` 里的 agent_program 基线、thunderagent_router 适配、swebench 并行工作流脚本。
5. ThunderAgent 作为"对照基线"的显式引用（旧 README 有，新 README 无）。

**被保留（kept）**
1. 模拟器 `emulation/workflow_emulation/` 整条线（两版本字节级同构）。
2. 普通请求路由四策略（least_load/least_latency/round_robin/session）与 foreign_load 逻辑。

**被增强（gained）**
1. stdlib-only 约束、wheel 打包（`vllm-hust-request-control-plane`）、`request_control_plane.__version__` 单一版本源。
2. Ray 托管路径打磨：`RouterService` actor、`RouterClient`、`ray_cluster_app.py` 单 job 提交、舰队 teardown 清理。
3. 运行时可观察/控制：`/stats` `/recent` `/state` `/policy`、`X-Control-Plane-*` 响应头、`CONTROL_PLANE_RESULTS_ROOT`。

---

## 六、对早前报告结论的修正

本会话早前对旧版 `main` 的深度报告（`wf-serving-report.md`）结论是："该仓库 = 独立 request control plane，其本质是 program_id 锚点的 program 容量限流（ThunderAgent 再实现）"。**这条结论对旧版 `main` 仍然成立，但 restructure 之后的走向把它推翻了**：

- 仓库的真实轨迹是"**先在在线控制面里做 program 限流（ThunderAgent 式），再决定把这套在线机制回退掉，只保留一个干净的请求路由器，把 workflow 调度研究降级到独立模拟器里做证据**"。
- 也就是说，program 限流被当成"需要先离线验证、不能直接放进生产控制面"的实验性机制，而不是"该仓库的长期内核"。新版把"内核"重新定义为"可打包的最小请求控制面 + 一个为它提供调度策略证据的 DAG 模拟器"。

如果用户后续工作要基于这个仓库，应以**新版（restructure）为准**：在线控制面是纯请求路由（`RequestController`），workflow 调度能力当前只存在于 `emulation/workflow_emulation/` 的轨迹回放里，尚未回到在线路径。

---

## 七、三条后续建议

1. **确认版本谱系**：新目录无 `.git`，建议 `git clone` 或 `gh repo view intellistream/vllm-workflow-aware-serving --branch <feature-control-plane-restructure 分支名>` 拿真实 commit 与 diff，验证"program 限流是被主动回退还是尚未合并"，这决定它是"终态"还是"中间态"。
2. **精读 `emulation/workflow_emulation/replay/discrete_event_replay.py` 与 `experiments/emulation/policy_matrix.py`**：既然 workflow-aware 的唯一在线资产在这里，理解它的调度策略矩阵（FCFS/SJF/ATLAS/critical-path）与"选 M1 候选"的判定门槛，是判断这条研究线下一步会往哪走的关键。
3. **对比新版 `request_controller.py` 与旧版 `program_throttling.py` 的差异是否已进 `CHANGELOG` 之外的文档**：新版 README 已不写 program 限流，若 `documents/design/agent_program_throttling.md`（旧版有）在新版也被删，说明官方口径是"program 限流不再是当前能力"，应据此更新对项目的理解。
