# Policy-verdict correction

| | |
|---|---|
| **Status** | `diagnostic` (a methodology correction, not a performance result) |
| **Date** | 2026-10-22 |
| **Code** | `56a8d6a` (oracle) through `4ac8cc5`; capture at `6acd2e5`, seed 300 |
| **Oracle** | `tau2-oracle-1:581044662966` (4 validators: return, enable roaming, refuel, payment request). Earlier versions `4899c603ad81` and `56256d59043f` are kept in the store. |
| **Decision** | Adopted. Every replay, gated pass and viewer since evaluates the gate against the deterministic pre-execution policy verdict (M6c). The trace match and the task outcome are secondary. |

## Question

Measured against an independent policy verdict, how often does "the task passed" or "the write
matched the reference trace" agree with "the write should have executed"?

## Dataset

- **Smoke run 2:** 12 completed simulations with the same tasks and models as smoke 1, and
  11 writes ([`capture-summary.json`](capture-summary.json),
  [`score-summary.json`](score-summary.json)).
- **Verdicts:** computed from the pre-action snapshot and the conversation only. The oracle never
  sees the backend's answer, the reward or any judge score.

## Result

- **Verdicts:** 4 ALLOW, 1 ASK, 6 DENY ([`verdict-crosstab.json`](verdict-crosstab.json)).
- **Trace match vs verdict:** of the 7 writes that matched τ²'s reference trace, only 4 were
  policy ALLOW; 1 was ASK and 2 DENY.
- **Task outcome vs verdict:** of the 7 writes in passing simulations, 3 should not have run.
- Regression fixtures (`tests/fixtures/verdicts/`) pin these cases.
- **Fixes on 2026-10-22:**
  - refuel needs the exact total presented;
  - a zero refuel is `AMOUNT_NOT_POSITIVE`;
  - a yes to the active plan confirms its order.
- The verdicts are unaudited: no human review was imported.

## Report

There is no separate report. Fixtures and tests: `tests/test_verdicts_regression.py`. The viewer
is the [judge and strategy comparison](../2026-10-22-judge-strategy-comparison/README.md).
