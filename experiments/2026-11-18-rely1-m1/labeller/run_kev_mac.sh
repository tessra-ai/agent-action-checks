#!/bin/bash
# Check 3 on Prithvi's Mac (2026-11-20): stock Kev-4B v1.0, untrained, on the same 125 requests
# Jev answered. Needs Apple Silicon, Xcode command-line tools (git) and an internet connection.
# Takes about an hour: a ~9 GB one-time download, then roughly 15-30 s per request.
# Output: kev4b_results.zip next to this script. Send that file back.
# Runs from the package `python stock_models.py package` builds (this script, stock_models.py and
# requests.jsonl in one folder), not from the repository checkout.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$PWD"
for f in stock_models.py requests.jsonl; do
  [ -f "$f" ] || { echo "Missing $f here: run this from the kev_mac package folder."; exit 1; }
done
KEV_COMMIT=2074cc44256200bb37540103fa4572901faa10f3   # the Kev code this project pinned in M0
MODEL=jaredpalmer/kev-4b@v1.0
PORT=8009

[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || { echo "Needs an Apple Silicon Mac."; exit 1; }
MEM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
echo "Memory: ${MEM_GB} GB"
if [ "$MEM_GB" -lt 32 ]; then
  echo "Kev's README lists Kev-4B for a 32 GB Mac. With ${MEM_GB} GB it may still work for these"
  echo "packets (mostly under 8k tokens), or run out of memory. Close other apps. Continuing in 10 s"
  echo "(Ctrl-C to stop)."; sleep 10
fi
command -v uv >/dev/null || { echo "Installing uv (Python tool manager)..."; curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }

if [ ! -d kev ]; then git clone -q https://github.com/jaredpalmer/kev.git kev; fi
git -C kev fetch -q origin && git -C kev checkout -q "$KEV_COMMIT"
[ "$(git -C kev rev-parse HEAD)" = "$KEV_COMMIT" ] || { echo "Could not check out Kev $KEV_COMMIT"; exit 1; }
(cd kev && uv sync -q --extra serve)

if curl -s -o /dev/null "http://localhost:$PORT/" 2>/dev/null; then
  echo "Something is already using port $PORT; stop it (or edit PORT in this script) and rerun."; exit 1
fi
echo "Starting Kev-4B (the first start downloads the model)..."
# Its own process group, so stopping it also stops the Python server uv starts.
set -m
(cd kev && exec uv run --extra serve python -m kev.serve --run "$MODEL" --port "$PORT" > "$HERE/kev_server.log" 2>&1) &
SERVER=$!
set +m
trap 'kill -- -$SERVER 2>/dev/null || kill $SERVER 2>/dev/null || true' EXIT
# Ready only when our own Kev process is alive and answers with a Kev model listing.
ready() { kill -0 $SERVER 2>/dev/null && curl -sf "http://localhost:$PORT/v1/models" | grep -q kev; }
for i in $(seq 1 360); do
  ready && break
  kill -0 $SERVER 2>/dev/null || { echo "Kev stopped; last lines of kev_server.log:"; tail -20 kev_server.log; exit 1; }
  sleep 10
done
ready || { echo "Kev did not start within an hour; see kev_server.log"; exit 1; }
echo "Kev is up. Scoring 125 requests (rerun this script to resume if it stops)..."
python3 stock_models.py run --name kev4b --url "http://localhost:$PORT/v1" --requests requests.jsonl --out out
sysctl -n machdep.cpu.brand_string > out/kev4b_machine.txt; echo "${MEM_GB} GB" >> out/kev4b_machine.txt
git -C kev rev-parse HEAD >> out/kev4b_machine.txt; echo "$MODEL" >> out/kev4b_machine.txt
(cd out && zip -qr "$HERE/kev4b_results.zip" kev4b kev4b_machine.txt)
echo "Done. Send kev4b_results.zip back."
