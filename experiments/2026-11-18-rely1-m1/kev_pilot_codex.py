"""Codex for the Kev pilot's planted data: writing edits (gen) and checking them (check).

    python kev_pilot_codex.py gen   [--scale 1] [--workers 3]
    python kev_pilot_codex.py check [--scale 1] [--workers 3]

Same isolation and sign-in as labeller A (labeller/run_codex.py: ChatGPT sign-in, no API key, a
private mount namespace, shell and exec tools off, a fresh ephemeral call per job), on the same
model and reasoning effort as labeller A (gpt-6.2-sol, high). Each job file holds the whole
message. A reply that fails its parser is rerun fresh, up to 3 attempts; a usage limit pauses the
run, and running it again resumes. Every attempt is logged (never a credential).

Codex is labeller A. Here it also writes about a third of the planted edits and checks every
planted edit, so the planted set leans toward labeller A's reading (kev_pilot_plan.md).
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kev_pilot as K  # noqa: E402

_spec = importlib.util.spec_from_file_location("run_codex", HERE / "labeller/run_codex.py")
RC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RC)

MODEL, EFFORT = "gpt-6.2-sol", "high"
EXTRA = ["-m", MODEL, "-c", f"model_reasoning_effort={EFFORT}"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["gen", "check"])
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    jobs_dir = K.OUT / f"{a.kind}_jobs_s{a.scale}"
    out = K.OUT / f"{a.kind}_s{a.scale}"
    (out / "answers").mkdir(parents=True, exist_ok=True)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    manifest = json.loads((jobs_dir / "manifest.json").read_text())
    for m in manifest:
        if K.sha((jobs_dir / m["file"]).read_bytes()) != m["sha256"]:
            raise SystemExit(f"{m['file']} changed since its manifest was written")
    version = RC.preflight()
    lock, paused = threading.Lock(), threading.Event()
    log = out / "log.jsonl"

    def parse(m: dict, text: str) -> None:
        if a.kind == "gen":
            K.parse_gen(text)
        else:
            K.parse_check(text, m["ids"])

    def done(m: dict) -> bool:
        f = out / "answers" / f"{m['job']}.json"
        d = out / "answers" / f"{m['job']}.sha256"
        if not f.exists() or not d.exists() or d.read_text().strip() != m["sha256"]:
            return False  # an answer counts only for the exact job text it answered
        try:
            parse(m, f.read_text())
            return True
        except Exception:
            return False

    def attempt(m: dict, n: int) -> str:
        raw = out / "raw" / f"{m['job']}.{n}"
        if raw.exists():
            shutil.rmtree(raw)
        raw.mkdir()
        env = {
            **RC.clean_env(),
            "CODEX_HOME_SRC": str(RC.CODEX_HOME),
            "CODEX_EXTRA": " ".join(EXTRA),
            "PACK_SRC": str(jobs_dir),
            "OUT_SRC": str(raw),
            "PACKET": m["file"],
        }
        start = dt.datetime.now(dt.UTC)
        proc = subprocess.Popen(
            ["unshare", "--mount", "--propagation", "private", "bash", "-c", RC.ISOLATE],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )  # fmt: skip
        try:
            _, perr = proc.communicate(timeout=1800)
            code, timed_out = proc.returncode, False
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            code, perr, timed_out = -9, "timeout", True
        stderr = (raw / "stderr.txt").read_text() if (raw / "stderr.txt").exists() else ""
        reply = (raw / "last.txt").read_text() if (raw / "last.txt").exists() else ""
        model = (RC.MODEL.search(stderr) or [None, None])[1]
        effort = (RC.EFFORT.search(stderr) or [None, None])[1]
        used = RC.TOKENS.search(stderr)
        problem = ""
        try:
            parse(m, reply)
        except Exception as e:
            problem = f"{type(e).__name__}: {e}"[:200]
        diagnostics = "\n".join(RC.ERROR_LINE.findall(stderr)) + "\n" + (perr or "")
        if timed_out:
            outcome = "timeout"
        elif problem and RC.LIMIT.search(diagnostics):
            outcome = "usage_limit"
        elif problem:
            outcome = "invalid"
        elif model != MODEL or effort != EFFORT:
            outcome = "model_or_effort_mismatch"
        else:
            outcome = "ok"
        row = {
            "job": m["job"],
            "attempt": n,
            "start": start.isoformat(timespec="seconds"),
            "seconds": round((dt.datetime.now(dt.UTC) - start).total_seconds(), 1),
            "exit": code,
            "model": model,
            "reasoning_effort": effort,
            "cli": version,
            "tokens_used": int(used.group(1).replace(",", "")) if used else None,
            "outcome": outcome,
            "problem": problem,
        }
        with lock, log.open("a") as f:
            f.write(json.dumps(row) + "\n")
        if outcome == "ok":
            (out / "answers" / f"{m['job']}.json").write_text(reply)
            (out / "answers" / f"{m['job']}.sha256").write_text(m["sha256"] + "\n")
        return outcome

    def one(m: dict) -> str:
        prior = [int(d.name.rsplit(".", 1)[1]) for d in (out / "raw").glob(f"{m['job']}.*")]
        first = max(prior, default=0) + 1
        for n in range(first, first + RC.ATTEMPTS):
            if paused.is_set():
                return "paused"
            r = attempt(m, n)
            if r == "ok":
                return r
            if r in ("usage_limit", "model_or_effort_mismatch"):
                paused.set()
                return r
        return "failed"

    todo = [m for m in manifest if not done(m) and (not a.only or m["job"] in a.only)]
    print(f"codex {version}; {a.kind}: {len(todo)} of {len(manifest)} jobs to run", flush=True)
    res = {}
    with ThreadPoolExecutor(a.workers) as ex:
        for m, r in zip(todo, ex.map(one, todo), strict=True):
            res[m["job"]] = r
            print(m["job"], r, flush=True)
    left = [j for j, r in res.items() if r != "ok"]
    print(f"done: {len(res) - len(left)} ok, {len(left)} not {' '.join(left)}")
    if paused.is_set():
        print("PAUSED (usage limit or model change); run again later to resume.")
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
