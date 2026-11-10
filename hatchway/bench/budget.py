"""A hard spend cap: every external call reserves its maximum cost before it starts.

The ledger lives in the benchmark store (`spend_ledger`), so the capture harness, the scorer and
any number of processes share it. A call:

1. reserves a conservative maximum (`reserve`). The reservation is refused, and the call never
   made, if it would take its category (`capture`, `scoring`) or the aggregate over its cap;
2. runs;
3. settles at its actual cost (`settle`), persisted at once. A call whose cost is unknown, or
   that failed in a way that may still be billed (a timeout, a dropped connection), settles at
   its reservation.

Committed spend counts settled calls at their actual cost and open reservations at their
maximum. A process killed mid-call leaves its reservation open, so the interrupted call is
counted at its maximum, never as free; `recover` closes such rows on restart. Every attempt of a
retried call is reserved separately.

Reserving and checking run in one `BEGIN IMMEDIATE` transaction, so two processes cannot both
take the last of a cap.
"""

from __future__ import annotations

import math
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS spend_ledger (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    identity     TEXT NOT NULL,
    category     TEXT NOT NULL,
    reserved_usd REAL NOT NULL CHECK (reserved_usd >= 0),
    actual_usd   REAL,
    status       TEXT NOT NULL CHECK (status IN ('reserved', 'settled', 'released')),
    reserved_ts  TEXT NOT NULL,
    settled_ts   TEXT,
    note         TEXT
);
CREATE INDEX IF NOT EXISTS spend_ledger_category ON spend_ledger (category, status);
"""


class BudgetRefused(Exception):
    """A call was refused before it started: its maximum cost would exceed a cap."""


@dataclass(frozen=True)
class Caps:
    """USD caps per category, and on the sum of all categories."""

    per_category: Mapping[str, float]
    total: float | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


class Ledger:
    """The spend ledger of one store file. Thread- and process-safe."""

    def __init__(self, path: str | Path, caps: Caps) -> None:
        self.path = Path(path)
        self.caps = caps
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False, timeout=60.0
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(LEDGER_DDL)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- Accounting ---------------------------------------------------------------------------

    def _committed(self, category: str | None) -> float:
        query = (
            "SELECT COALESCE(SUM(CASE status WHEN 'settled' THEN actual_usd "
            "WHEN 'reserved' THEN reserved_usd ELSE 0 END), 0) FROM spend_ledger"
        )
        params: tuple[Any, ...] = ()
        if category is not None:
            query += " WHERE category = ?"
            params = (category,)
        return float(self._conn.execute(query, params).fetchone()[0])

    def committed(self, category: str | None = None) -> float:
        """Settled spend plus open reservations, for `category` or for everything."""
        with self._lock:
            return self._committed(category)

    def remaining(self, category: str) -> float:
        """What a new reservation in `category` may still take."""
        with self._lock:
            return self._remaining(category)

    def _remaining(self, category: str) -> float:
        left = [self.caps.per_category.get(category, math.inf) - self._committed(category)]
        if self.caps.total is not None:
            left.append(self.caps.total - self._committed(None))
        return max(0.0, min(left))

    def summary(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT category, status, COUNT(*), COALESCE(SUM(reserved_usd), 0), "
                "COALESCE(SUM(actual_usd), 0) FROM spend_ledger GROUP BY category, status"
            ).fetchall()
            out: dict[str, Any] = {
                "caps": {**self.caps.per_category, "total": self.caps.total},
                "committed": {"total": self._committed(None)},
                "rows": [
                    {
                        "category": c,
                        "status": s,
                        "calls": n,
                        "reserved_usd": r,
                        "actual_usd": a,
                    }
                    for c, s, n, r, a in rows
                ],
            }
            for c in {r[0] for r in rows} | set(self.caps.per_category):
                out["committed"][c] = self._committed(c)
        return out

    # --- Reserve, settle ----------------------------------------------------------------------

    def reserve(self, identity: str, category: str, max_usd: float) -> int:
        """Reserve `max_usd` for one call, or raise `BudgetRefused`. Returns the row id."""
        if not math.isfinite(max_usd) or max_usd < 0:
            raise ValueError(f"reservation must be a finite non-negative amount, not {max_usd}")
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                left = self._remaining(category)
                if max_usd > left:
                    raise BudgetRefused(
                        f"{identity}: reserving ${max_usd:.6f} would exceed the {category} or "
                        f"total cap (${left:.6f} left)"
                    )
                cur = self._conn.execute(
                    "INSERT INTO spend_ledger (identity, category, reserved_usd, status, "
                    "reserved_ts) VALUES (?, ?, ?, 'reserved', ?)",
                    (identity, category, max_usd, _now()),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
        return int(cur.lastrowid)

    def settle(self, reservation: int, actual_usd: float | None, note: str = "") -> None:
        """Close a reservation at the call's actual cost; unknown cost settles at the
        reservation (the conservative choice)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT reserved_usd, status FROM spend_ledger WHERE id = ?", (reservation,)
            ).fetchone()
            if row is None or row[1] != "reserved":
                raise KeyError(f"no open reservation {reservation}")
            actual = row[0] if actual_usd is None else float(actual_usd)
            if actual > row[0] * (1 + 1e-9):
                # The estimate was too low: recorded as it is, and flagged for review.
                note = f"over reservation by ${actual - row[0]:.6f}; {note}".rstrip("; ")
            self._conn.execute(
                "UPDATE spend_ledger SET status = 'settled', actual_usd = ?, settled_ts = ?, "
                "note = ? WHERE id = ?",
                (actual, _now(), note or None, reservation),
            )

    def release(self, reservation: int, note: str = "") -> None:
        """Close a reservation whose call was certainly never sent: it costs nothing."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE spend_ledger SET status = 'released', actual_usd = 0, settled_ts = ?, "
                "note = ? WHERE id = ? AND status = 'reserved'",
                (_now(), note or None, reservation),
            )
        if cur.rowcount != 1:
            raise KeyError(f"no open reservation {reservation}")

    def recover(self) -> int:
        """On restart: settle every reservation a dead process left open at its maximum.
        Returns how many. Call only when no other process is using the ledger."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE spend_ledger SET status = 'settled', actual_usd = reserved_usd, "
                "settled_ts = ?, note = 'interrupted: counted at its reservation' "
                "WHERE status = 'reserved'",
                (_now(),),
            )
        return cur.rowcount

    @contextmanager
    def call(self, identity: str, category: str, max_usd: float) -> Iterator[_Call]:
        """Reserve, run the body, settle. Set `.cost` in the body to the actual cost; if the
        body raises or leaves the cost unknown, the call settles at its reservation."""
        reservation = self.reserve(identity, category, max_usd)
        handle = _Call()
        try:
            yield handle
        except BaseException:
            self.settle(reservation, None, note="failed: counted at its reservation")
            raise
        self.settle(
            reservation, handle.cost, note="" if handle.cost is not None else "cost unknown"
        )


@dataclass
class _Call:
    cost: float | None = None


# --- Conservative maxima ------------------------------------------------------------------------


def chars_to_tokens(text_chars: int) -> int:
    """An upper estimate of tokens for `text_chars` characters of English or JSON text: one
    token per 2 characters (tokenizers average about 4)."""
    return math.ceil(text_chars / 2) + 16


def llm_call_max_usd(
    input_tokens: int, max_output_tokens: int, usd_per_input: float, usd_per_output: float
) -> float:
    """The most one call can cost: every input token uncached, the full output allowance."""
    return input_tokens * usd_per_input + max_output_tokens * usd_per_output


MaxCost = Callable[..., float]
