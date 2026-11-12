# E9 — Mod 形态与验收（开工稿）

日期：2026-10-29　　状态：**脚手架已落盘，真机 A/B 未跑**

## 1. 为什么要一个 Mod

路线图的 C3 要求"一个可独立部署的 controller 进程 + 开关 + 验收 A/B"。当前 `executor` 是"永远开启"的服务，无法做 A/B：对照组必须能让它**完全退回不存在时的行为**。

## 2. 形态：三种调用关系，一种进程

```
client → TA(:9000) → mod(:9002) → card-A(:8110) / card-B(:10.244.0.76:8110)
```

`mod` 是**一个进程、三种模式**（启动参数决定，运行期只读文件开关）：

| 模式 | 参数 | 行为 |
|---|---|---|
| `passthrough` | `--mode passthrough` | 按 `X-Target-Instance` 或轮询直连卡片，**不做放置、不迁移**（= 裸 TA 的等价物） |
| `affinity` | `--mode affinity` | program→卡 亲和放置；不迁移 |
| `affinity+migrate` | `--mode affinity --migrate` | 上面 + 平衡器（recompute 或 transfer 载体） |

运行期开关：`--kill-switch <file>`，文件存在则**立即降级为 passthrough**（不改代码、不重启）。`GET /healthz` 回报 `mode`、`kill_switch`、`moves`、`programs`。

## 3. 三条验收（判据已按 C1-v3 改口径）

| # | 场景 | 对照 | 判据 |
|---|---|---|---|
| A1 | 压力档（每卡需求 ≥ 1.1× 容量，合成 agent 负载） | `passthrough` | **TTFT p95 与 token 速率均不劣于对照 5%**；若靠搬家则要求 p95 改善 ≥10% |
| A2 | 日常档（每卡 ≤ 0.8×） | `passthrough` | 不劣 3%（不应有回归） |
| A3 | 真实 agent（mini-swe-agent，`job_id` 已坐实） | `passthrough` | TTFT p50/p95 不劣；`step/min` 不作判据，只记录 |

三列都必须给：通关 / 不达标 / 解释；A1 不达标就写"当前平台该形态不成立"。

## 4. 复现步骤（A/B 成对）

```bash
# 1) 两台引擎分别起（单卡各一）
ssh -p 31475 root@223.92.35.180 'bash /root/e5/start_plain.sh'
ssh -p 32666 root@223.92.35.180 'bash /root/e5/start_plain.sh'

# 2) 起 mod（对照臂用 passthrough，实验臂用 affinity+migrate）
python3 -m mod.cli --listen 9002 --mode affinity --migrate \
  --card a=http://127.0.0.1:8110 --card b=http://10.244.0.76:8110 \
  --kill-switch /tmp/mod.kill

# 3) TA 只认识 mod 一个后端
python3 /root/m2/ta_launch.py --backends http://127.0.0.1:9002 --port 9000

# 4) 跑同一批实例，采 TTFT 直方图差分
```

降级验证：`touch /tmp/mod.kill` 后 `GET /healthz` 应报 `mode=passthrough`，且下一个请求不再产生 `moves`.

## 5. 与已有部件的关系

- 放置/迁移逻辑**复用** `llumnix-ray-pathA` 与 `program-executor/executor` 的 program 表与平衡器，不重写；
- `mod` 只做三件事：多卡路由表、开关、健康回报；
- 卡数与 `/metrics` 口径：每卡一个 upstream，绝不聚合（E5 的 0.73× 就是聚合造成的）。

## 6. 未做

- 真机 A/B（A1/A2/A3 三行）；
- `passthrough` 与"TA 直连两卡"的等价性验证（需一次同批跑对比，确认 mod 本身不引入开销）；
- 打包（wheel/容器镜像）。
