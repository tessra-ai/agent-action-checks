"""WRIT-2K re-check: user overlap counted from any mention, and a wider confirmation list.

python3 -I writ_check_definitions.py WRIT-2K.json unseen_rows.json
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
UID = re.compile(r"\b[a-z]+_[a-z]+_\d{3,4}\b")
tu = {str(t["id"]): {u for u in UID.findall(json.dumps(t)) if u in users} for t in tasks}


def g(t):
    return "unseen" if t in UNSEEN else "repeat" if t in REPEAT else "other"


per = C()
unseen_rows = set()
for i, r in enumerate(rows):
    if r["domain"] != "airline":
        continue
    text = json.dumps([m for m in r["messages"] if m.get("role") != "system"])
    u = {x for x in UID.findall(text) if x in users}
    hit = [t for t, us in tu.items() if us & u]
    if hit:
        k = sorted({g(t) for t in hit}, key=["unseen", "repeat", "other"].index)[0]
        per[k] += 1
        if k == "unseen":
            unseen_rows.add(i)
print("any mention in messages:", sum(per.values()), dict(per))
a = json.loads(Path(sys.argv[2]).read_text())
print(
    "unseen rows same as tool-arg definition:",
    unseen_rows == {o["row"] for o in a["unseen"]},
    len(unseen_rows),
)
# confirmation: last user turn before the write, any of a wider word list
W = re.compile(
    r"\b(yes|yeah|yep|proceed|confirm\w*|go ahead|please do|that's (right|correct)|correct"
    r"|ok(ay)?|sure)\b",
    re.I,
)
WRITE = {
    "book_reservation",
    "cancel_reservation",
    "update_reservation_flights",
    "update_reservation_passengers",
    "update_reservation_baggages",
    "send_certificate",
}
n = t = 0
for r in rows:
    if r["domain"] != "airline":
        continue
    prev = ""
    for m in r["messages"]:
        if m.get("role") == "user":
            prev = m.get("content") or ""
        for tc in m.get("tool_calls") or []:
            if tc["function"]["name"] in WRITE:
                t += 1
                n += bool(W.search(prev))
print("writes after a user turn with a wider confirmation list:", n, "of", t)
