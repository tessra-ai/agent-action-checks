"""Check 3 (Prithvi, 2026-11-20): stock, untrained Jev and Kev-4B on the direct
material-contradiction question. PROVISIONAL: scored against the model labellers' consensus,
not a person's labels.

    python stock_models.py build                       # -> runs/stock_models/requests.jsonl
    python stock_models.py run --name jev              # Jev via TypeSafe (TYPESAFE_API_KEY)
    python stock_models.py run --name kev4b --url http://localhost:8009/v1   # a local Kev server
    python stock_models.py summarize                   # -> results/stock_models.json

`build` writes one System One request per statement packet (the 125 packets of the labeller
pack that hold statement questions, train and dev only): the state is the packet text, the same
as the labellers saw, without its "# Questions" list; each statement is one yes/no ("noul")
question whose instructions are the labellers' statement-question wording (prompt.txt, "QUESTION
TYPE 1") followed by the quoted sentence and its turn. `run` sends them one by one and keeps
every raw reply (runs/stock_models/<name>/, git-ignored); it needs only the Python standard
library, so the same file runs on a Mac against a local Kev server. `summarize` reports, at
P(yes) cut-offs 0.3 / 0.5 / 0.7 / 0.9, how many of the both-yes statements each model catches
and how many both-no statements it flags, under and over 8,192 tokens, with cost where known.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACK = HERE / "runs/labeller_pack"
OUT = HERE / "runs/stock_models"
R = HERE / "results"
CUTS = (0.3, 0.5, 0.7, 0.9)
JEV_URL = "https://api.typesafe.ai/v1"
JEV_MODEL = "jev-1.14.0"  # as pinned in hatchway/judges/jev.py
JEV_USD_PER_INPUT_TOKEN = 0.042 / 1_000_000


def statement_wording() -> str:
    """The labellers' statement question, verbatim from prompt.txt."""
    text = (PACK / "prompt.txt").read_text(encoding="utf-8")
    start = text.index("QUESTION TYPE 1: STATEMENTS")
    end = text.index('Allowed answers: "yes", "no", "not_sure".', start)
    body = text[start:end].split("\n", 1)[1].strip()
    return body + (
        "\n\nAnswer yes (a material contradiction) or no. The sentence to judge follows."
    )


def build() -> None:
    m = json.loads((PACK / "manifest.json").read_text())
    key = json.loads((R / "pack_key.json").read_text())
    rows = {
        r["unit_key"]: r for r in map(json.loads, (R / "label_set.jsonl").read_text().splitlines())
    }
    wording = statement_wording()
    OUT.mkdir(parents=True, exist_ok=True)
    lines = []
    for c in m["calls"]:
        if not c["call"].endswith("-S"):
            continue
        pid = c["call"].split("-")[0]
        text = (PACK / c["file"]).read_text(encoding="utf-8")
        state = text.split("\n# Questions\n", 1)[0].rstrip() + "\n"
        questions = {}
        for q in c["questions"]:
            u = rows[key[pid]["questions"][q["id"]]]["unit"]
            quote = f"(T{u['turn']}"
            if u["lead_in"]:
                quote += f", a list item under: {json.dumps(u['lead_in'], ensure_ascii=False)}"
            quote += f") {json.dumps(u['text'], ensure_ascii=False)}"
            questions[q["id"].replace(".", "_")] = {
                "type": "noul",
                "instructions": f"{wording}\n\n{quote}",
            }
        lines.append({"call": c["call"], "state": state, "questions": questions})
    path = OUT / "requests.jsonl"
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))
    print(len(lines), "requests,", sum(len(x["questions"]) for x in lines), "questions ->", path)
    print("sha256", hashlib.sha256(path.read_bytes()).hexdigest())


def post(url: str, body: dict, key: str | None, timeout: int = 900) -> dict:
    req = urllib.request.Request(
        url.rstrip("/") + "/systemone",
        data=json.dumps(body).encode(),
        headers={
            "content-type": "application/json",
            **({"authorization": f"Bearer {key}"} if key else {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run(name: str, url: str, model: str, key_env: str | None, requests: Path, out: Path) -> None:
    key = os.environ.get(key_env) if key_env else None
    if key_env and not key:
        raise SystemExit(f"{key_env} is not set")
    out = out / name
    out.mkdir(parents=True, exist_ok=True)
    reqs = [json.loads(x) for x in requests.read_text().splitlines()]
    for i, x in enumerate(reqs, 1):
        f = out / f"{x['call']}.json"
        body = {"model": model, "state": x["state"], "questions": x["questions"]}
        digest = hashlib.sha256(
            json.dumps({"url": url, "body": body}, sort_keys=True).encode()
        ).hexdigest()  # the backend and the request
        if f.exists():  # resume only over a reply to this very request
            if json.loads(f.read_text()).get("request_sha256") == digest:
                continue
            raise SystemExit(f"{f} answers a different request; move {out} aside and rerun")
        for attempt in range(4):
            try:
                t0 = time.time()
                resp = post(url, body, key)
                break
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:300]
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(10 * (attempt + 1))
                    continue
                raise SystemExit(f"{x['call']}: HTTP {e.code}: {msg}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 3:
                    time.sleep(10 * (attempt + 1))
                    continue
                raise SystemExit(f"{x['call']}: {e}") from None
        f.write_text(
            json.dumps(
                {
                    "call": x["call"],
                    "request_sha256": digest,
                    "seconds": round(time.time() - t0, 2),
                    "response": resp,
                }
            )
        )
        print(f"{i}/{len(reqs)} {x['call']}", flush=True)
    print("done:", name)


def summarize() -> None:
    a = {r["id"]: r for r in map(json.loads, (R / "labels_a.jsonl").read_text().splitlines())}
    b = {r["id"]: r for r in map(json.loads, (R / "labels_b.jsonl").read_text().splitlines())}
    key = json.loads((R / "pack_key.json").read_text())
    rows = {
        r["unit_key"]: r for r in map(json.loads, (R / "label_set.jsonl").read_text().splitlines())
    }
    length = {
        q: rows[u]["length"] for v in key.values() for q, u in v["questions"].items() if ".S" in q
    }
    both_yes = {q for q in length if a[q]["answer"] == b[q]["answer"] == "yes"}
    both_no = {q for q in length if a[q]["answer"] == b[q]["answer"] == "no"}
    out = {
        "status": "PROVISIONAL, MODEL-LABELLED: truth is the consensus of labeller A and B "
        "(both yes / both no); no person has reviewed it. Train and dev only. Stock models, "
        "untrained.",
        "both_yes": len(both_yes),
        "both_no": len(both_no),
        "models": {},
    }
    replies = [
        p for p in OUT.iterdir() if p.is_dir() and any(p.glob("P*-S.json"))
    ]  # model reply folders only (not the Mac package)
    for d in sorted(replies):
        p_yes, tokens, secs, model_ids = {}, 0, [], set()
        for f in d.glob("*.json"):
            x = json.loads(f.read_text())
            resp = x["response"]
            model_ids.add(resp.get("model"))
            tokens += (resp.get("usage") or {}).get("input_tokens") or 0
            secs.append(x["seconds"])
            for name, ans in resp["answers"].items():
                p_yes[name.replace("_", ".", 1)] = float(ans["noul"])
        res = {
            "model_ids": sorted(filter(None, model_ids)),
            "questions_scored": len(p_yes),
            "input_tokens": tokens,
            "median_seconds_per_call": statistics.median(secs) if secs else None,
        }
        if d.name == "jev":
            res["cost_usd"] = round(tokens * JEV_USD_PER_INPUT_TOKEN, 4)
        for band in ("all", "under_8192", "over_8192"):
            yes = [q for q in both_yes if band == "all" or length[q] == band]
            no = [q for q in both_no if band == "all" or length[q] == band]
            res[band] = {
                "both_yes_n": len(yes),
                "both_no_n": len(no),
                "missing": sum(q not in p_yes for q in yes + no),
                **{
                    f"cut_{c}": {
                        "both_yes_caught": sum(p_yes.get(q, -1) >= c for q in yes),
                        "both_no_flagged": sum(p_yes.get(q, -1) >= c for q in no),
                    }
                    for c in CUTS
                },
            }
        res["p_yes_both_yes"] = {q: round(p_yes[q], 4) for q in sorted(both_yes) if q in p_yes}
        out["models"][d.name] = res
    (R / "stock_models.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: {b: v[b] for b in ("all",)} for k, v in out["models"].items()}, indent=1))


def package() -> None:
    """runs/stock_models/kev_mac.zip: run_kev_mac.sh, this file, requests.jsonl and a HOWTO."""
    import shutil

    d = OUT / "kev_mac"
    if d.exists():  # a clean package: no earlier run output inside it
        shutil.rmtree(d)
    d.mkdir(parents=True)
    shutil.copy2(Path(__file__), d / "stock_models.py")
    shutil.copy2(HERE / "labeller/run_kev_mac.sh", d / "run_kev_mac.sh")
    shutil.copy2(OUT / "requests.jsonl", d / "requests.jsonl")
    (d / "HOWTO.txt").write_text(HOWTO)
    zipped = shutil.make_archive(str(OUT / "kev_mac"), "zip", OUT, "kev_mac")
    print(zipped)


HOWTO = """KEV-4B ON YOUR MAC (check 3)

1. Unzip this folder anywhere (for example in Downloads).
2. Open Terminal, then type:  cd   (with a space), drag the unzipped folder into the
   Terminal window, and press Enter.
3. Run:  ./run_kev_mac.sh
   - It checks the Mac, installs what it needs, downloads Kev-4B (about 9 GB, once),
     starts it on your Mac, answers the 125 requests, and stops it.
   - Expect about an hour. Keep the Mac awake and plugged in.
   - If it stops part-way, run ./run_kev_mac.sh again: it carries on where it left off.
4. When it says "Done", send me kev4b_results.zip (it is in the same folder).

Nothing leaves your Mac except the downloads of Kev's code and model. The requests are the
same public tau2 conversations the labellers saw.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    r = sub.add_parser("run")
    r.add_argument("--name", required=True, help="jev or kev4b")
    r.add_argument("--url", default=JEV_URL)
    r.add_argument("--model", default=None)
    r.add_argument(
        "--key-env", default=None, help="env var holding the bearer key (jev: TYPESAFE_API_KEY)"
    )
    r.add_argument("--requests", default=str(OUT / "requests.jsonl"))
    r.add_argument("--out", default=str(OUT))
    sub.add_parser("summarize")
    sub.add_parser("package", help="the folder and zip for the Mac (Kev-4B)")
    a = ap.parse_args()
    if a.cmd == "build":
        build()
    elif a.cmd == "run":
        is_jev = a.name == "jev"
        model = a.model or (JEV_MODEL if is_jev else "kev-latest")
        key_env = a.key_env or ("TYPESAFE_API_KEY" if is_jev else None)
        run(a.name, a.url, model, key_env, Path(a.requests), Path(a.out))
    elif a.cmd == "package":
        package()
    else:
        summarize()


if __name__ == "__main__":
    sys.exit(main())
