#!/bin/bash
# The Gemini resume loop (README, Deviations). Up to ~1h50m: one chunk at a time; after a probe
# Google refuses (503 overload) wait 15 minutes; stop when nothing is left, or on Google's daily
# limit. Usage: run_gemini_loop.sh <docent-venv python> <cap usd>
#   rebuild the venv: python3 -m venv V && V/bin/pip install -r requirements-docent.txt
set -u
PY="$1"; CAP="$2"
cd "$(dirname "$0")/../.."
end=$(($(date +%s) + 6600))
i=0
while [ "$(date +%s)" -lt "$end" ]; do
  i=$((i+1))
  echo "=== attempt $i $(date -u +%H:%M:%S)"
  HATCH_JUDGE_RESUME=1 HATCH_JUDGE_CAP_USD="$CAP" HATCH_JUDGE_STRIP_FENCES=1 HATCH_JUDGE_TIMEOUT_S=600 \
  HATCH_JUDGE_CONCURRENCY=2 HATCH_JUDGE_RETRIES=3 HATCH_JUDGE_CHUNK=7 \
    "$PY" experiments/2026-11-05-judges-other-providers/judge_provider.py \
    google gemini-3.1-pro-preview airline1 results/gemini_airline1.jsonl 80 > "runs/gemini_attempt_$i.log" 2>&1
  grep -a "^probe\|^projected\|^wrote\|nothing left\|not starting\|cap reached" "runs/gemini_attempt_$i.log"
  grep -aq "nothing left to judge" "runs/gemini_attempt_$i.log" && { echo "all judged"; break; }
  grep -aq "PerDay" "runs/gemini_attempt_$i.log" && { echo "daily quota exhausted"; break; }
  grep -aq "not starting" "runs/gemini_attempt_$i.log" && { echo "waiting 900s"; sleep 900; }
done
echo "loop done $(date -u +%H:%M:%S)"
