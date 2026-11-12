"""Make kv_role=kv_both start BOTH the sending and the receiving thread.

Upstream vllm-ascend `mooncake_connector` branches on `kv_role == "kv_producer"`
and puts everything else in an `else` that only builds the receiving side.  A
`kv_both` engine therefore ends up with no `KVCacheSendingThread` at all: a peer
that pulls from it waits forever, and the engine can only ever be a destination.

Six anchors below turn those role tests into membership tests, so `kv_both` gets
both threads and reports both directions' completions.  `kv_producer` and
`kv_consumer` behaviour is unchanged (the membership sets are supersets).

Target: /vllm-workspace/vllm-ascend/vllm_ascend/distributed/kv_transfer/kv_p2p/mooncake_connector.py
Idempotent: re-running a patched tree reports applied=0.
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(
    "/vllm-workspace/vllm-ascend/vllm_ascend/distributed/kv_transfer/kv_p2p/mooncake_connector.py"
)

EDITS = [
    # 1. start the sending thread for kv_both too
    (
        '        if self.kv_role == "kv_producer":\n            self.kv_send_thread = KVCacheSendingThread(',
        '        if self.kv_role in ("kv_producer", "kv_both"):\n            self.kv_send_thread = KVCacheSendingThread(',
    ),
    # 2. the old `else:` becomes an explicit consumer/both branch, so kv_both
    #    gets a receiving thread as well instead of choosing one or the other
    (
        '            self.kv_send_thread.start()\n        else:\n            self.kv_recv_thread = KVCacheRecvingThread(',
        '            self.kv_send_thread.start()\n        if self.kv_role in ("kv_consumer", "kv_both"):\n            self.kv_recv_thread = KVCacheRecvingThread(',
    ),
    # 3. readiness wait must look at the thread we actually started
    (
        '        thread = self.kv_send_thread if self.kv_role == "kv_producer" else self.kv_recv_thread',
        '        thread = (\n            self.kv_send_thread\n            if self.kv_role in ("kv_producer", "kv_both")\n            else self.kv_recv_thread\n        )',
    ),
    # 4. finished sends
    (
        '            if self.kv_role == "kv_producer"\n            else set()\n        )\n        done_recving = (',
        '            if self.kv_role in ("kv_producer", "kv_both")\n            else set()\n        )\n        done_recving = (',
    ),
    # 5. finished receives
    (
        '            if self.kv_role == "kv_consumer"\n            else set()\n        )\n        if self.tp_rank == 0:',
        '            if self.kv_role in ("kv_consumer", "kv_both")\n            else set()\n        )\n        if self.tp_rank == 0:',
    ),
    # 6. load-error reporting comes back through the receiving side
    (
        '        if self.kv_role == "kv_consumer" and self.kv_recv_thread is not None:',
        '        if self.kv_role in ("kv_consumer", "kv_both") and self.kv_recv_thread is not None:',
    ),
]


def main() -> int:
    if not SRC.exists():
        print(f"missing {SRC}")
        return 2
    text = SRC.read_text(encoding="utf-8")
    applied = skipped = 0
    for old, new in EDITS:
        if new in text:
            skipped += 1
            continue
        if old not in text:
            print(f"anchor not found:\n{old[:90]}...")
            return 3
        text = text.replace(old, new, 1)
        applied += 1
    if applied:
        SRC.write_text(text, encoding="utf-8")
    print(f"applied={applied} skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
