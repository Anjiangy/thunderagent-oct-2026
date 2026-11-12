# 正式 mod：program 放置与容量的策略层

把 ThunderAgent 的核心策略（**按 program 放置 + 按 token 记账 + 暂停优先、迁移其次**）抽成一个
独立的 HTTP 服务，可以挂在任意 OpenAI 兼容的后端前面，不依赖 ThunderAgent 本体。

## 三种模式

| 模式 | 行为 | 用途 |
|---|---|---|
| `passthrough` | 轮询、无记忆 | 对照组 = 普通 LB |
| `affinity` | program 钉在首次落到的卡上 | 复现 TA 的 `tr` 模式 |
| `sticky` | 每次重估，**只在"不是自己把卡占满"时才移动**（减法滞回） | 想避免"自己挤自己"的误判 |

## 负载记账

```
load(program) = max( len(text) / 3.6 , usage.total_tokens )      # 估算与实际取大
held(card)    = Σ load + BUFFER_PER_PROGRAM(=100) × program_count
```

与上游 ThunderAgent 的常量保持一致，便于与论文/上游行为对齐。

## 启动

```bash
python3 -m mod.cli \
  --listen 9000 \
  --card a=http://127.0.0.1:8110 --card b=http://127.0.0.1:8122 \
  --capacity a=114176 --capacity b=114176 \
  --mode affinity \
  --kill-switch /tmp/sticky.off
```

- `--mode`：`passthrough` / `affinity` / `sticky`
- `--card NAME=URL`、`--capacity NAME=TOKENS`：可重复，声明后端与单卡 KV 容量
- `--kill-switch FILE`：该文件存在时强制退回 `passthrough`（线上应急，不需要重启）

客户端请求带 `program_id`（body 或 `x-session-id` 头），同 `program_id` 的请求保持同卡。

## 测试

```bash
python3 -m pytest mod/tests -q
```

`mod/policy.py` 是纯函数（无 Web 框架依赖），`mod/tests/test_ta_like.py` 与
`test_mod_placement.py` 覆盖：容量判定、暂停优先、迁移条件、滞回、kill switch。

## 与上游的关系

- 策略等价于 ThunderAgent 的"容量感知放置 + 暂停/恢复"；
- 差异：这里不做 KV 搬运，只做**放置与准入**；搬运相关的实验在十月的 M6/M12 文档里，
  结论是"搬不如重算"，除非前缀很长且有明确的回归窗口。