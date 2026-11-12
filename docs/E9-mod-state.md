# E9 Mod 状态（2026-10-30）：部署版本被我覆盖，改动需重建

## 现在机器上是什么

`/root/mod/cli.py` 目前是**仓库里的简版**（`mod/cli.py`，115 行）：只有 `passthrough` / `affinity` 两种模式，选卡逻辑是 `passthrough` 轮询、`affinity` 用 `hash(program_id) % len(cards)`。没有 `load_tokens`、没有 `programs_pinned`、没有 `moves`。

## 怎么变成这样的（如实记录）

1. 服务器上原本有一版**功能更全的实现**（`load_tokens` 按 `len(prompt)/3.6` 估计、`programs_pinned`、`moves` 计数），但那版从未回写到仓库。
2. 我尝试加 `usage.total_tokens` 计量，在服务器上直接改，结果服务起不来（无 traceback）。
3. 回退时先 `scp` 了本地 `mod/cli.py` 过去——**这一步把服务器上的富版覆盖掉了**；随后的 revert 脚本作用在这份简版上，等于没恢复。
4. 结果：富版丢失，现网是简版。已跑出的数据（TA 76.88%、Mod affinity 74.00%）是在富版上测的，仍然有效，但**无法在不重建的前提下复现**。

## 教训

- 服务器上的改动必须**先回写仓库再改**：本次富版没有 commit，一次 scp 就没了。
- 恢复动作要先确认目标文件内容（`md5sum`/行数），再覆盖。
- 本次 usage 补丁的失败原因仍未定位（`ast.parse` 与 `import` 都过，但 uvicorn 起不来），下次要在本地起服务验证。

## 待做（按顺序）

1. 在本地把富版能力重建进 `mod/cli.py`（`load_tokens` + `programs_pinned` + `moves` + `--mode sticky`），并用 `tests/test_mod_placement.py` 覆盖选卡逻辑；
2. 加 `usage` 计量：流式响应外包一层只读生成器抓 `"total_tokens"`，`load()` 取 `max(估计, 实测)`；
3. 本地 `uvicorn` 起一遍 + 单请求验证 `load_tokens` 变成真实量级，再 scp；
4. 用同一组"6 长 + 6 短"负载复测，与 TA 的 76.88% 并列。

在此之前，E9 这一格的结论维持：**Mod（集中放置）74.00% < 裸 TA（均衡）76.88%**。
