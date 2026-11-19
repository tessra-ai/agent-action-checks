"""Labeller A: OpenAI's default Codex model on Prithvi's ChatGPT sign-in, one packet per call.

    python experiments/2026-11-18-rely1-m1/labeller/run_codex.py [--workers 3]

Resumable: a call whose answer file already passes `ingest.py --call` is skipped. Run it again
after a pause (usage limit) and it carries on, on the same model (the default model is recorded
for every call; a change is refused).

Each call runs `codex exec` fresh, with:
- no API key: the environment is rebuilt from scratch (proxy and CA settings only), and the
  sign-in is ChatGPT (`codex login status` is checked first);
- its own Codex home (`/root/.codex-labeller-a`, holding only a copy of the ChatGPT sign-in
  file), `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, and memories, apps, plugins
  and skills off, so no earlier session, memory or connector reaches it; the shell and exec
  tools off, so the model cannot run a command or read a file (not even the sign-in copy that the
  CLI itself needs);
- a private mount namespace in which /home/user (every repo), /root (other than the CA bundle
  and that Codex home), /tmp and /old_root are empty; the working directory is a fresh temp
  directory holding only a copy of the labeller pack; `--sandbox read-only`;
- the message on stdin: prompt.txt followed directly by the packet file, unchanged.

A reply that fails `ingest.py --call` (refused, cut off, malformed) is rerun fresh, never
continued, up to 3 attempts. A usage limit pauses the run. Every attempt is logged to
`runs/labeller_a/log.jsonl` (date, call, attempt, model, CLI version, tokens, outcome; never a
credential). Raw replies go to `runs/labeller_a/` (git-ignored).
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
M1 = HERE.parent
PACK = M1 / "runs/labeller_pack"
OUT = M1 / "runs/labeller_a"
EXTRA: list[str] = []  # extra codex exec arguments (model pin, reasoning effort)
WANT_EFFORT: str | None = None
CODEX_HOME = Path("/root/.codex-labeller-a")
ATTEMPTS = 3
KEEP_ENV = (
    "PATH", "LANG", "LC_ALL", "TERM",
    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
    "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
)  # fmt: skip
LIMIT = re.compile(
    r"usage limit|rate limit|quota|too many requests|\b429\b|try again (at|in)", re.I
)
ERROR_LINE = re.compile(r"^(?:ERROR|error|stream error)\b.*$", re.M)
MODEL = re.compile(r"^model:\s*(\S+)", re.M)
EFFORT = re.compile(r"^reasoning effort:\s*(\S+)", re.M)
TOKENS = re.compile(r"tokens used\s*\n?\s*([\d,]+)", re.I)

ISOLATE = r"""
set -e
mkdir -p /run/keep/ccr /run/keep/home /run/keep/pack /run/keep/out
mount --bind /root/.ccr /run/keep/ccr
mount --bind "$CODEX_HOME_SRC" /run/keep/home
mount --bind -o ro "$PACK_SRC" /run/keep/pack
mount --bind "$OUT_SRC" /run/keep/out
mount -t tmpfs none /root
mkdir -p /root/.ccr /root/.codex-labeller-a
mount --bind /run/keep/ccr /root/.ccr
mount --bind /run/keep/home /root/.codex-labeller-a
mount -t tmpfs none /home/user
[ -d /old_root ] && mount -t tmpfs none /old_root
mount -t tmpfs none /tmp
WORK=$(mktemp -d /tmp/labeller.XXXXXX)
cp -r /run/keep/pack "$WORK/labeller_pack"
cd "$WORK"
cat "$WORK/labeller_pack/prompt.txt" "$WORK/labeller_pack/$PACKET" | \
  codex exec --ephemeral --skip-git-repo-check --ignore-user-config --ignore-rules \
    --sandbox read-only --color never \
    --disable memories --disable apps --disable plugins --disable remote_plugin \
    --disable plugin_sharing --disable skill_search --disable skill_mcp_dependency_install \
    --disable shell_tool --disable unified_exec --disable sleep_tool --disable tool_suggest \
    $CODEX_EXTRA -C "$WORK" -o /run/keep/out/last.txt - \
    > /run/keep/out/stdout.txt 2> /run/keep/out/stderr.txt
"""


def _ingest():
    spec = importlib.util.spec_from_file_location("pack_ingest", PACK / "ingest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def clean_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
    env.update(HOME="/root", CODEX_HOME=str(CODEX_HOME))
    return env


def preflight() -> str:
    env = clean_env()
    if not (CODEX_HOME / "auth.json").exists():
        CODEX_HOME.mkdir(mode=0o700, exist_ok=True)
        shutil.copy2(Path("/root/.codex/auth.json"), CODEX_HOME / "auth.json")
    st = subprocess.run(
        ["codex", "login", "status"], env=env, capture_output=True, text=True, check=False
    )
    status = (st.stdout + st.stderr).strip()
    if "ChatGPT" not in status:
        raise SystemExit(f"labeller A must use the ChatGPT sign-in, not an API key: {status!r}")
    ver = subprocess.run(["codex", "--version"], env=env, capture_output=True, text=True)
    return ver.stdout.strip()


class Run:
    def __init__(self, workers: int):
        self.version = preflight()
        self.ingest = _ingest()
        self.manifest = self.ingest.load_manifest(PACK / "manifest.json")
        self.lock = threading.Lock()
        self.paused = threading.Event()
        self.workers = workers
        (OUT / "answers").mkdir(parents=True, exist_ok=True)
        # One runner per output tree, for the whole run.
        self._lock_file = (OUT / "run.lock").open("w")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("another labeller A runner is using runs/labeller_a") from None
        (OUT / "raw").mkdir(parents=True, exist_ok=True)
        self.log_path = OUT / "log.jsonl"
        # Saved replies are reused only for the pack they answered (prompt and every packet).
        fp = {
            "manifest_sha256": hashlib.sha256((PACK / "manifest.json").read_bytes()).hexdigest(),
            "prompt_sha256": hashlib.sha256((PACK / "prompt.txt").read_bytes()).hexdigest(),
        }
        for c in json.loads((PACK / "manifest.json").read_text())["calls"]:
            if hashlib.sha256((PACK / c["file"]).read_bytes()).hexdigest() != c["sha256"]:
                raise SystemExit(f"{c['file']} does not match the manifest; rebuild the pack")
        fp_path = OUT / "pack_fingerprint.json"
        if fp_path.exists() and json.loads(fp_path.read_text()) != fp:
            raise SystemExit("the labeller pack changed since this run started; not resuming")
        fp_path.write_text(json.dumps(fp, indent=1) + "\n")
        self.model = None
        if self.log_path.exists():  # the run's model is that of its accepted answers
            models = {
                r["model"]
                for r in map(json.loads, self.log_path.read_text().splitlines())
                if r.get("outcome") == "ok" and r.get("model")
            }
            if len(models) > 1:
                raise SystemExit(f"accepted answers come from more than one model: {models}")
            accepted = [
                r
                for r in map(json.loads, self.log_path.read_text().splitlines())
                if r.get("outcome") == "ok"
            ]
            if WANT_EFFORT and any(r.get("reasoning_effort") != WANT_EFFORT for r in accepted):
                raise SystemExit(f"accepted answers here were not made at effort {WANT_EFFORT}")
            pinned = EXTRA[EXTRA.index("-m") + 1] if "-m" in EXTRA else None
            if pinned and any(r.get("model") != pinned for r in accepted):
                raise SystemExit(f"accepted answers here were not made by {pinned}")
            self.model = models.pop() if models else None

    def done(self, call: str) -> bool:
        f = OUT / "answers" / f"{call}.json"
        if not f.exists():
            return False
        problems, _, _ = self.ingest.check([(str(f), f.read_text())], self.manifest, call=call)
        return not problems

    def log(self, row: dict) -> None:
        with self.lock, self.log_path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def attempt(self, call: dict, n: int) -> str:
        name = call["call"]
        raw = OUT / "raw" / f"{name}.{n}"
        if raw.exists():
            shutil.rmtree(raw)
        raw.mkdir()
        env = {
            **clean_env(),
            "CODEX_HOME_SRC": str(CODEX_HOME),
            "CODEX_EXTRA": " ".join(EXTRA),
            "PACK_SRC": str(PACK),
            "OUT_SRC": str(raw),
            "PACKET": call["file"],
        }
        start = dt.datetime.now(dt.UTC)
        proc = subprocess.Popen(
            ["unshare", "--mount", "--propagation", "private", "bash", "-c", ISOLATE],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )  # fmt: skip
        try:
            out, err = proc.communicate(timeout=1800)
            p = subprocess.CompletedProcess([], proc.returncode, out, err)
            timed_out = False
        except subprocess.TimeoutExpired:  # stop the whole tree, Codex included
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            p = subprocess.CompletedProcess([], -9, "", "timeout")
            timed_out = True
        end = dt.datetime.now(dt.UTC)
        stderr = (raw / "stderr.txt").read_text() if (raw / "stderr.txt").exists() else ""
        reply = (raw / "last.txt").read_text() if (raw / "last.txt").exists() else ""
        model = (MODEL.search(stderr) or [None, None])[1]
        effort = (EFFORT.search(stderr) or [None, None])[1]
        used = TOKENS.search(stderr)
        usage = int(used.group(1).replace(",", "")) if used else None
        problems = self.ingest.check([(name, reply)], self.manifest, call=name)[0]
        # Only the CLI's own error lines count, never the transcript (which echoes the packet).
        diagnostics = "\n".join(ERROR_LINE.findall(stderr)) + "\n" + p.stderr
        limited = bool(LIMIT.search(diagnostics)) and bool(problems)
        outcome = (
            "ok"
            if not problems and not timed_out
            else "timeout"
            if timed_out
            else "usage_limit"
            if limited
            else "invalid"
        )
        with self.lock:
            if outcome == "ok" and WANT_EFFORT and effort != WANT_EFFORT:
                outcome = "effort_mismatch"  # never accept a reply at another reasoning effort
            elif outcome == "ok" and not model:
                outcome = "model_unknown"  # never accept an answer whose model is unverified
            elif model and self.model and model != self.model:
                outcome = "model_changed"
            elif model and not self.model:
                self.model = model
        self.log(
            {
                "call": name,
                "attempt": n,
                "date": start.date().isoformat(),
                "start": start.isoformat(timespec="seconds"),
                "seconds": round((end - start).total_seconds(), 1),
                "exit": p.returncode,
                "model": model,
                "reasoning_effort": effort,
                "cli": self.version,
                "tokens_used": usage,
                "outcome": outcome,
                "problems": problems[:5],
                "isolation_error": p.stderr.strip()[-300:] if p.returncode and not stderr else "",
            }
        )
        if outcome == "ok":
            (OUT / "answers" / f"{name}.json").write_text(reply)
        return outcome

    def one(self, call: dict) -> str:
        # Attempt numbers carry on from earlier runs, so raw replies are never overwritten.
        with self.lock:
            prior = [
                json.loads(x)["attempt"]
                for x in (self.log_path.read_text().splitlines() if self.log_path.exists() else [])
                if json.loads(x)["call"] == call["call"]
            ]
        prior += [
            int(d.name.rsplit(".", 1)[1])
            for d in (OUT / "raw").glob(f"{call['call']}.*")
            if d.name.rsplit(".", 1)[1].isdigit()
        ]
        first = max(prior, default=0) + 1
        for n in range(first, first + ATTEMPTS):
            if self.paused.is_set():
                return "paused"
            outcome = self.attempt(call, n)
            if outcome == "ok":
                return "ok"
            if outcome in ("usage_limit", "model_changed", "model_unknown", "effort_mismatch"):
                self.paused.set()
                return outcome
        return "failed"

    def run(self) -> int:
        todo = [c for c in self.manifest[0]["calls"] if not self.done(c["call"])]
        print(f"codex {self.version}; {len(todo)} calls to run", flush=True)
        results: dict[str, str] = {}
        with ThreadPoolExecutor(self.workers) as ex:
            for c, r in zip(todo, ex.map(self.one, todo), strict=True):
                results[c["call"]] = r
                print(c["call"], r, flush=True)
        left = [c for c, r in results.items() if r != "ok"]
        print(f"done: {len(results) - len(left)} ok, {len(left)} not ({' '.join(left)})")
        if self.paused.is_set():
            print("PAUSED (usage limit or model change); rerun later to resume.")
        return 0 if not left else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", nargs="*", help="run just these calls (e.g. a smoke test)")
    ap.add_argument("--out", help="output folder under runs/ (default labeller_a)")
    ap.add_argument("--model", help="pin the model (e.g. gpt-6.2-sol)")
    ap.add_argument("--effort", help="reasoning effort (e.g. high)")
    a = ap.parse_args()
    global OUT, WANT_EFFORT
    if a.out:
        OUT = M1 / "runs" / a.out
    if a.model:
        EXTRA.extend(["-m", a.model])
    if a.effort:
        EXTRA.extend(["-c", f"model_reasoning_effort={a.effort}"])
        WANT_EFFORT = a.effort
    r = Run(a.workers)
    if a.only:
        calls = [
            c for c in r.manifest[0]["calls"] if c["call"] in set(a.only) and not r.done(c["call"])
        ]
        return 0 if all(r.one(c) == "ok" for c in calls) else 1
    return r.run()


if __name__ == "__main__":
    sys.exit(main())
