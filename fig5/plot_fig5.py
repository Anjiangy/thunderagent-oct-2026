# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

N = [24, 48, 72, 96]
vllm_tp  = [1598.03, 375.97, 328.81, 301.80]
ta_tp    = [1779.48, 2445.96, 1366.70, 1198.37]
vllm_hit = [87.70, 39.06, 25.90, 0.05]
ta_hit   = [92.82, 92.81, 83.45, 82.81]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.4), dpi=150)

ax1.plot(N, vllm_tp, 'o-', color='#d62728', lw=2.5, ms=7, label='vLLM (round-robin baseline)')
ax1.plot(N, ta_tp, 's-', color='#1f77b4', lw=2.5, ms=7, label='ThunderAgent (ours, tr)')
ax1.set_xlabel('Concurrency (N programs)', fontsize=12)
ax1.set_ylabel('Throughput (steps / min)', fontsize=12)
ax1.set_title('(a) Throughput - Qwen2.5-14B, 2x910B2', fontsize=13)
ax1.set_xticks(N)
ax1.grid(True, alpha=0.3)
ax1.legend(fontsize=10, loc='best')
sp = ta_tp[-1] / vllm_tp[-1]
ax1.annotate(f'{sp:.2f}x vs vLLM', xy=(96, ta_tp[-1]), xytext=(78, ta_tp[-1]*0.75),
             fontsize=11, fontweight='bold', color='#1f77b4',
             arrowprops=dict(arrowstyle='->', color='#1f77b4'))

ax2.plot(N, vllm_hit, 'o-', color='#d62728', lw=2.5, ms=7, label='vLLM (round-robin baseline)')
ax2.plot(N, ta_hit, 's-', color='#1f77b4', lw=2.5, ms=7, label='ThunderAgent (ours, tr)')
ax2.set_xlabel('Concurrency (N programs)', fontsize=12)
ax2.set_ylabel('KV cache hit rate (%)', fontsize=12)
ax2.set_title('(b) KV cache hit rate', fontsize=13)
ax2.set_xticks(N)
ax2.set_ylim(0, 105)
ax2.grid(True, alpha=0.3)
ax2.legend(fontsize=10, loc='best')
ax2.annotate(f'{vllm_hit[-1]:.2f}%', xy=(96, vllm_hit[-1]), xytext=(72, 18),
             fontsize=12, fontweight='bold', color='#d62728',
             arrowprops=dict(arrowstyle='->', color='#d62728'))
ax2.annotate(f'{ta_hit[-1]:.1f}%', xy=(96, ta_hit[-1]), xytext=(70, 58),
             fontsize=12, fontweight='bold', color='#1f77b4',
             arrowprops=dict(arrowstyle='->', color='#1f77b4'))

fig.suptitle('ThunderAgent Figure 5 reproduction (unique per-program long prefix)', fontsize=13.5, y=1.02)
fig.tight_layout()
fig.savefig('fig5_reproduction.png', bbox_inches='tight')
print('saved fig5_reproduction.png')
print('N=96 speedup =', round(sp, 2), 'x')
