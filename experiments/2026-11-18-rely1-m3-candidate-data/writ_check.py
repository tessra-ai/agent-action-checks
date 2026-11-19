"""WRIT-2K re-check by Claude (audit only): rows, write calls, overlap with tau2 task users.

python3 -I writ_check.py WRIT-2K.json unseen_rows.json
"""

import collections
import json
import re
import sys
from pathlib import Path

TAU2 = Path(__file__).parents[2] / ".tau2-bench/data/tau2/domains/airline"

C = collections.Counter
rows = json.loads(Path(sys.argv[1]).read_text())
tasks = json.loads((TAU2 / "tasks.json").read_text())
db = json.loads((TAU2 / "db.json").read_text())
UNSEEN = {"5", "6", "8", "18", "19", "26", "27", "28", "30", "39", "47"}
REPEAT = {
    "1",
    "7",
    "9",
    "11",
    "12",
    "13",
    "15",
    "16",
    "17",
    "20",
    "21",
    "22",
    "23",
    "24",
    "25",
    "31",
    "33",
    "35",
    "37",
    "38",
    "40",
    "41",
    "43",
    "44",
    "45",
    "48",
}
users = set(db["users"])
res = set(db["reservations"])
UID = re.compile(r"\b[a-z]+_[a-z]+_\d{3,4}\b")
RID = re.compile(r"\b[A-Z0-9]{6}\b")
task_users = {}
task_res = {}
for t in tasks:
    s = json.dumps(t)
    task_users[str(t["id"])] = {u for u in UID.findall(s) if u in users}
    task_res[str(t["id"])] = {r for r in RID.findall(s) if r in res}


def group(tid):
    return "unseen" if tid in UNSEEN else "repeat" if tid in REPEAT else "other"


print("rows", len(rows), C(r["domain"] for r in rows))
air = [(i, r) for i, r in enumerate(rows) if r["domain"] == "airline"]
WRITE = {
    "book_reservation",
    "cancel_reservation",
    "update_reservation_flights",
    "update_reservation_passengers",
    "update_reservation_baggages",
    "send_certificate",
}
nw = C()
traj_w = 0
confirm = 0
total = 0
overlap = []
per = C()
res_ov = C()
for i, r in air:
    msgs = r["messages"]
    has = False
    prev_user = ""
    uids = set()
    rids = set()
    for m in msgs:
        if m.get("role") == "user":
            prev_user = m.get("content") or ""
        for tc in m.get("tool_calls") or []:
            f = tc["function"]
            name = f["name"]
            args = f["arguments"]
            args = json.loads(args) if isinstance(args, str) else args
            if "user_id" in args:
                uids.add(args["user_id"])
            if "reservation_id" in args:
                rids.add(args["reservation_id"])
            if name in WRITE:
                nw[name] += 1
                has = True
                total += 1
                if re.search(r"\b(yes|proceed|confirm)", prev_user, re.I):
                    confirm += 1
    traj_w += has
    hit = [tid for tid, us in task_users.items() if us & uids]
    if hit:
        g = sorted({group(t) for t in hit}, key=["unseen", "repeat", "other"].index)[0]
        per[g] += 1
        overlap.append(
            {
                "row": i,
                "group": g,
                "tasks": sorted(hit, key=int),
                "users": sorted(set().union(*[task_users[t] for t in hit]) & uids),
            }
        )
        rh = [t for t in hit if task_res[t] & rids]
        if rh:
            res_ov[sorted({group(t) for t in rh}, key=["unseen", "repeat", "other"].index)[0]] += 1
print("airline writes", total, dict(nw), "trajectories with a write", traj_w)
print("writes right after a user turn with yes/proceed/confirm", confirm)
print(
    "trajectories using a task user",
    len(overlap),
    dict(per),
    "also a task reservation",
    dict(res_ov),
)
Path(sys.argv[2]).write_text(
    json.dumps({"unseen": [o for o in overlap if o["group"] == "unseen"]}, indent=1)
)
