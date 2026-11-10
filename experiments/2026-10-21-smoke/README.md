# Smoke run 1: task and backend outcomes as labels

| | |
|---|---|
| **Status** | `diagnostic` · `superseded` (by [the policy-verdict correction](../2026-10-22-policy-verdicts/README.md)) |
| **Date** | 2026-10-21 |
| **Code** | Not recorded in the outputs; `main` was at `1374043` (store schema 1, `hatchway_version` 0.0.1) |
| **Decision** | Do not use τ² task outcomes or trace matches as the gate's ground truth. Build an independent policy verdict instead (M6c). |

## Question

Does the capture → score → replay pipeline run end to end on real τ² simulations? Do its labels
mean what the gate needs them to mean?

## Dataset

- **Simulations:** 12, from retail tasks 10 and 13 and one telecom roaming task, each run by
  `gpt-4.1-nano`, `-mini` and `gpt-4.1`.
- **Task passes:** retail 5/6, telecom 4/6.
- **Writes:** 11, scored by three judges for $0.0775
  ([`score-summary.json`](score-summary.json)).
- **Labels:** the τ² trace match of each write: 7 correct, 3 incorrect, 1 ambiguous.

## Result

- **The pipeline ran end to end**
  ([`capture-summary.json`](capture-summary.json), [`replay-metrics.json`](replay-metrics.json)).
- **The labels were the wrong target.**
  - **Task 10:** two refunds went to the other order's payment method. The backend rejected both
    and the task still passed.
  - **Task 13:** a PayPal refund matched τ²'s reference trace yet broke the refund rule.
  - A write's trace match, the backend's answer and the simulation's reward each differ from the
    question the gate asks: may this write execute now, under the written policy?
- **No arm comparison is meaningful** on these labels; the held-out set is 6 writes from one task.

## Report

There is no Git report. The HTML viewer (`runs/report/index.html`, sha256
`f75bb488cd214355ae87f0489fe53d0840d77971f96b62ad33dc4dfcfa903485`) is local. The store is
`runs/smoke.db` (sha256 `db88947be4ff3c088e5b549f544917df514145c0e0cf884692caa5c22f14a7c1`).
