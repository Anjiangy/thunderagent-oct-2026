#!/bin/bash
set -u
cd /root/e10 || exit 1
: > /root/e10/keep2.jsonl; : > /root/e10/keep2.err
for arm in off naive gated; do
  echo "=== arm=$arm start $(date +%H:%M:%S)"
  E10_ARM="$arm" E10_PROGRAMS=4 E10_WORDS=3500 E10_TURNS=4 E10_GAP=20 \
    timeout 900 python3 -u /root/e10_keep_cost.py >> /root/e10/keep2.jsonl 2>> /root/e10/keep2.err
  echo "=== arm=$arm rc=$? at $(date +%H:%M:%S)"
done
echo "---- rows"
cat /root/e10/keep2.jsonl
echo "---- err tail"
tail -5 /root/e10/keep2.err