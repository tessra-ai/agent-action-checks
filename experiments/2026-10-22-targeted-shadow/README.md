# Targeted shadow experiment (stage 1)

| | |
|---|---|
| **Status** | `diagnostic` · `superseded` (stopped at stage 1; its captures were reused by the [decision-model pilot](../2026-10-23-decision-model-pilot/Decision-Model%20Pilot.md)) |
| **Date** | 2026-10-22 |
| **Code / manifest** | `29b5af7`; definition sha256 `21bd172117dc5c171f1ca419c4143ef251b507677feee30c4393c081f270cf56` ([`experiment.json`](experiment.json)); split sha256 `7bfa51a68f4d03415e77e611d1e16373766ab1c82a0f0bb9bca3de6d93539148` ([`split.json`](split.json)) |
| **Oracle** | `tau2-oracle-1:581044662966` |
| **Decision** | `INCONCLUSIVE`; the pre-scoring sample gates did not pass ([`decision.json`](decision.json)). The experiment was stopped on request before scoring or stages 2–3. |

## Question

On the four validated action types (returns, enable roaming and refuel as primary actions;
payment requests descriptive only), does a fitted model (E) or a two-judge combination (F) cut
escalations by at least 10% relative to D on held-out data, with no worse safety?

## Dataset

- **Stage 1:** 57 completed simulations, 19 tasks × 3 agent models; $2.59 capture spend against
  a $12 hard cap ([`final-count.json`](final-count.json)).
- **Writes:** 68 primary writes, 65 with a verdict.
  - Returns: 15 ALLOW, 7 ASK, 22 DENY, 1 UNKNOWN.
  - Roaming: 10 ALLOW, 3 DENY.
  - Refuel: 1 ALLOW, 6 ASK, 1 DENY, 2 UNKNOWN.

## Result

- **The family split put 59 writes in training and 9 in the held-out set.** Its greedy "first
  past 60%" rule overshot the target.
- **The held-out sample gates failed.** There were 9 verdict-bearing writes against a minimum of
  70, and too few per action ([`gate.json`](gate.json)).
- **Lessons:**
  - refuel ALLOW is scarce;
  - telecom costs more than estimated;
  - the split must land closest to its target, not first past it.

## Report

- **HTML viewer:** "Targeted Experiment Viewer" (not published; built from the local build
  below, with an INCONCLUSIVE banner).
- **Local build:** `runs/targeted/report/index.html`, sha256
  `0f872d05d8ae2c59b03f451b26e4ad388b939abd851d365917853042bd8e4cb0`.
- **Store:** `runs/targeted.db`. It now also holds the pilot's scores; see the pilot report for
  its sha256.
