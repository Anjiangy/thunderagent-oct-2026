# 台架事故记录：B 卡引擎死掉 → TA 半残 → 客户端挂 40 分钟

## 现象
32 program 的 TA 臂跑了 40+ 分钟没有任何输出，`data/e12d_sweep.csv` 只有表头；tm4 上 `minisweagent.run.extra.swebench` 进程还活着（8 workers），TA `/health` 显示 `programs_count=0`、两张卡 `total=0`。

## 根因（两层）
1. **B 卡引擎没起来**（`32425` 上 `health=000`，日志 `RuntimeError: Engine core initialization failed`）。TA 的 backend 列表仍写着 `http://10.244.1.31:8110`，请求打到死 backend 就永久等 → 客户端 8 个 worker 全卡住，TA 侧看不到任何 program（请求还没进路由就被连接卡死）。
2. **扫测脚本的断言不够**：只断言了"`num_gpu_blocks=892` 出现"，而这个值是从 A 的 `/metrics` 拿的，B 死着也能过。

## 修法
1. B 上按 PID 杀掉残留（`ps -eo pid,args | awk`，**不能用 `pkill -f`，pattern 在命令行里会自杀**）→ `bash /root/e5/start_plain.sh` → 等 100 s 拿到 `health=200`、`num_gpu_blocks=892`。
2. 本机重建两条隧道（`-L 18100/18104/18110` 到 A，`-L 18111` 到 B，`-R 18100/18104` 到 tm4），实测 `18110=200 / 18111=200 / TA=200`。
3. sweep 脚本加 **preflight**：三个 health 不过就 abort，不再烧一小时。

## 复现命令
```bash
# 台架体检（本机）
foreach ($p in 18100,18104,18110,18111) { curl -s -o /dev/null -w "$p=%{http_code}`n" http://127.0.0.1:$p/health }
# B 卡重启（在 32425 上）
bash /root/e5/b_up.sh      # 内含按 PID 清理 + start_plain.sh + 轮询 health
```
