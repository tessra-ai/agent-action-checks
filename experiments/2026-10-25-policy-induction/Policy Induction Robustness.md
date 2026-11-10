# Policy Induction: Robustness Pack

> Controlled benchmark built from τ²-bench retail data and its deterministic oracle. Demonstrates mechanism behavior only; does not establish real organizational performance.

| | |
|---|---|
| **Status** | `diagnostic` |
| **Results** | R1 replication pass · R3 targeted audits pass · R4 certified exceptions pass · R2 and R5 descriptive |
| **Data** | Fresh generator seed 20261026: 789 families, 7784 cases; split {'cert': 148, 'test': 323, 'train': 318} |
| **Random rules** | 94 escalation and 20 relaxation rules from the preregistered grammar (seed 20261026) |
| **Spend** | $0.00; 0 external calls |

Preregistration: [`RFC-robustness.md`](RFC-robustness.md). Phase A ([`RFC.md`](RFC.md)) is unchanged.

## R1: Replication on a fresh seed

Frozen Phase A sweep on the fresh cases: outcome there `BENCHMARK_TOO_HARD`; checks {'A1_shuffled_control': True, 'A2_learnable': False, 'A3_discriminating': True}. Worlds within one k step of Phase A: 13 of 13 (bar 11).

| World | k* Phase A | k* fresh seed | Within one step |
|---|---|---|---|
| C_AUTH | 5 | 5 | yes |
| C_CONFIRM | 5 | 5 | yes |
| C_OWNER | 5 | 5 | yes |
| C_REASON | 5 | 5 | yes |
| C_REFUND | 5 | 5 | yes |
| C_STATUS | 5 | 5 | yes |
| H1_LARGE_REFUND | 10 | 20 | yes |
| H2_PRODUCT | — | — | yes |
| H3_REPEAT_CANCEL | 10 | 10 | yes |
| H4_UPCHARGE | 5 | 5 | yes |
| H5_CHARGEBACK | — | — | yes |
| H6_SMALL_CANCEL_WAIVER | — | — | yes |
| H7_PAYPAL_RETURN | — | — | yes |

Fresh-seed learnable worlds (A2): H3_REPEAT_CANCEL, H4_UPCHARGE.

## R2: Randomly drawn rules (arm S, clean labels)

Share of rules recovered (recovery rate ≥ 0.8 across 10 replicates) within k examples.

| Rule type | Rules | k* ≤ 5 | k* ≤ 10 | k* ≤ 20 |
|---|---|---|---|---|
| escalate · 1 cond (num) · any action | 39 | 27 | 36 | 38 |
| escalate · 1 cond (num) · one action | 10 | 0 | 1 | 5 |
| escalate · 1 cond (payment_source) · any action | 3 | 3 | 3 | 3 |
| escalate · 1 cond (products) · any action | 13 | 13 | 13 | 13 |
| escalate · 1 cond (user_state) · any action | 3 | 3 | 3 | 3 |
| escalate · 2 cond (num) · any action | 12 | 2 | 3 | 7 |
| escalate · 2 cond (num) · one action | 1 | 0 | 0 | 1 |
| escalate · 2 cond (num+payment_source) · any action | 6 | 0 | 2 | 6 |
| escalate · 2 cond (num+payment_source) · one action | 3 | 0 | 0 | 2 |
| escalate · 2 cond (num+user_state) · any action | 2 | 1 | 2 | 2 |
| escalate · 2 cond (payment_source+user_state) · any action | 1 | 0 | 1 | 1 |
| escalate · 2 cond (payment_source+user_state) · one action | 1 | 0 | 1 | 1 |
| relax · 1 cond (num) · any action | 5 | 0 | 1 | 5 |
| relax · 1 cond (num) · one action | 3 | 0 | 0 | 1 |
| relax · 1 cond (payment_source) · any action | 3 | 0 | 1 | 3 |
| relax · 1 cond (products) · any action | 1 | 1 | 1 | 1 |
| relax · 1 cond (user_state) · any action | 1 | 0 | 1 | 1 |
| relax · 2 cond (num) · any action | 2 | 0 | 0 | 2 |
| relax · 2 cond (num+payment_source) · any action | 2 | 0 | 0 | 1 |
| relax · 2 cond (num+payment_source) · one action | 1 | 0 | 0 | 0 |
| relax · 2 cond (payment_source+user_state) · any action | 1 | 0 | 0 | 0 |
| relax · 2 cond (payment_source+user_state) · one action | 1 | 0 | 0 | 0 |
| **All** | 114 | 50 | 69 | 96 |

By how often the rule fires (share of in-scope cases it changes):

| Fires on | Rules | Recovered within 10 |
|---|---|---|
| > 10% | 77 | 42 |
| 5-10% | 37 | 27 |

## R3: Pricing audits

Cells (rule, k) where some audit rate reached recovery: 119; targeted needed at most half of random's rate in 60 (bar: half of the cells). Targeted-shuffled control any-rule rate: 0.002 (bar 0.05).

Needed audit rate (smallest with recovery ≥ 0.8; — none up to 100%):

| World | Train triggering families | k=10 random / targeted | k=20 random / targeted | k=40 random / targeted |
|---|---|---|---|---|
| R2-E001 | 42 | 1.0 / 1.0 | 1.0 / 0.5 | 1.0 / 0.5 |
| R2-E002 | 78 | 0.5 / 0.5 | 0.5 / 0.25 | 0.25 / 0.25 |
| R2-E003 | 43 | 0.5 / 0.5 | 0.5 / 0.25 | 0.25 / 0.25 |
| R2-E005 | 46 | 0.5 / 0.5 | 0.5 / 0.25 | 0.25 / 0.25 |
| R2-E007 | 50 | 1.0 / 0.5 | 0.25 / 0.25 | 0.25 / 0.25 |
| R2-E013 | 54 | 0.5 / 0.5 | 0.5 / 0.25 | 0.25 / 0.25 |
| R2-E015 | 50 | 0.5 / 0.5 | 0.5 / 0.25 | 0.25 / 0.25 |
| R2-E017 | 53 | 0.5 / 0.5 | 0.5 / 0.25 | 0.25 / 0.25 |
| R2-E019 | 73 | 1.0 / 0.5 | 0.5 / 0.25 | 0.25 / 0.25 |
| R2-E020 | 82 | 0.5 / 0.5 | 0.5 / 0.5 | 0.5 / 0.25 |
| R2-E021 | 75 | 0.5 / 1.0 | 0.5 / 0.25 | 0.25 / 0.25 |
| R2-E022 | 43 | — / — | 1.0 / 0.5 | 1.0 / 0.5 |
| R2-E023 | 40 | — / — | 1.0 / 1.0 | 1.0 / 0.5 |
| R2-E029 | 72 | 0.5 / 0.25 | 0.5 / 0.25 | 0.25 / 0.25 |
| R2-E030 | 41 | — / — | 1.0 / — | 1.0 / — |
| R2-E032 | 42 | 1.0 / 1.0 | 0.5 / 0.5 | 0.5 / 0.5 |
| R2-E034 | 49 | 1.0 / 0.5 | 1.0 / 0.25 | 0.5 / 0.25 |
| R2-E039 | 65 | 0.5 / 0.5 | 0.5 / 0.25 | 0.5 / 0.25 |
| R2-E041 | 41 | — / — | 1.0 / 1.0 | 1.0 / 0.5 |
| R2-E042 | 53 | 0.5 / 0.5 | 0.5 / 0.5 | 1.0 / 0.25 |
| R2-E043 | 49 | 1.0 / 1.0 | 1.0 / 1.0 | 0.5 / 0.5 |
| R2-E045 | 69 | 0.5 / 0.5 | 0.5 / 0.25 | 0.25 / 0.25 |
| R2-E047 | 53 | 1.0 / 1.0 | 0.5 / 0.5 | 0.25 / 0.5 |
| R2-E050 | 50 | 1.0 / 0.5 | 0.5 / 0.5 | 1.0 / 0.25 |
| R2-E051 | 80 | 1.0 / 0.5 | 0.5 / 0.25 | 0.25 / 0.25 |
| R2-E055 | 89 | 1.0 / 0.5 | 1.0 / 0.5 | 0.25 / 0.5 |
| R2-E058 | 72 | 1.0 / 1.0 | 1.0 / 0.25 | 0.5 / 0.25 |
| R2-E059 | 58 | 0.5 / 1.0 | 1.0 / 0.5 | 0.5 / 0.5 |
| R2-E061 | 48 | 1.0 / — | 1.0 / — | 1.0 / 1.0 |
| R2-E064 | 63 | 1.0 / 0.5 | 1.0 / 0.5 | 1.0 / 0.5 |
| R2-E065 | 67 | 0.5 / 0.5 | 0.5 / 0.25 | 0.5 / 0.25 |
| R2-E066 | 72 | 1.0 / 0.5 | 0.5 / 0.5 | 0.5 / 0.25 |
| R2-E072 | 66 | 1.0 / 0.5 | 0.5 / 0.25 | 0.5 / 0.25 |
| R2-E077 | 44 | 1.0 / 1.0 | 1.0 / 0.5 | 0.5 / 0.25 |
| R2-E081 | 54 | 1.0 / 1.0 | 1.0 / 0.5 | 1.0 / 0.5 |
| R2-E085 | 86 | 0.5 / 0.5 | 0.5 / 0.5 | 1.0 / 0.5 |
| R2-E086 | 89 | 1.0 / 0.5 | 0.5 / 0.5 | 1.0 / 0.5 |
| R2-E087 | 86 | 1.0 / 0.25 | 0.5 / 0.25 | 0.5 / 0.25 |
| R2-E089 | 65 | — / 1.0 | 0.5 / 0.5 | 0.5 / 0.25 |
| R2-E093 | 55 | 1.0 / 1.0 | 1.0 / 0.5 | 1.0 / 0.25 |
| R2-E094 | 52 | — / 1.0 | 0.5 / 0.5 | 0.5 / 0.5 |

## R4: Specific, certified exceptions

Pooled out-of-sample failure rate among test families where an exception allowed a case: S 0.469 (14042/29939), S-cert 0.000 (0/934). Bar: S-cert ≤ 0.10 and S > 0.10.

| World | k | S catch · failing families | S-cert catch · failing families | Exceptions certified |
|---|---|---|---|---|
| H6_SMALL_CANCEL_WAIVER | 10 | 0.87 · 42.5 | 0.00 · 0.0 | 0.00 |
| H6_SMALL_CANCEL_WAIVER | 20 | 0.88 · 24.4 | 0.00 · 0.0 | 0.00 |
| H6_SMALL_CANCEL_WAIVER | 5 | 0.42 · 23.0 | 0.00 · 0.0 | 0.00 |
| R2-R001 | 10 | 1.00 · 55.8 | 0.00 · 0.0 | 0.00 |
| R2-R001 | 20 | 1.00 · 11.9 | 0.00 · 0.0 | 0.00 |
| R2-R001 | 5 | 0.00 · 0.0 | 0.00 · 0.0 | 0.00 |
| R2-R002 | 10 | 0.93 · 41.7 | 0.00 · 0.0 | 0.00 |
| R2-R002 | 20 | 1.00 · 10.0 | 0.00 · 0.0 | 0.00 |
| R2-R002 | 5 | 0.17 · 9.8 | 0.00 · 0.0 | 0.00 |
| R2-R003 | 10 | 0.97 · 0.4 | 0.17 · 0.0 | 0.20 |
| R2-R003 | 20 | 0.99 · 0.9 | 0.27 · 0.0 | 0.30 |
| R2-R003 | 5 | 0.68 · 13.1 | 0.00 · 0.0 | 0.00 |
| R2-R004 | 10 | 1.00 · 47.7 | 0.00 · 0.0 | 0.00 |
| R2-R004 | 20 | 1.00 · 31.0 | 0.00 · 0.0 | 0.00 |
| R2-R004 | 5 | 0.50 · 29.5 | 0.00 · 0.0 | 0.00 |
| R2-R005 | 10 | 1.00 · 6.8 | 0.00 · 0.0 | 0.00 |
| R2-R005 | 20 | 1.00 · 0.0 | 0.00 · 0.0 | 0.00 |
| R2-R005 | 5 | 0.80 · 47.6 | 0.00 · 0.0 | 0.00 |
| R2-R006 | 10 | 1.00 · 7.7 | 0.00 · 0.0 | 0.00 |
| R2-R006 | 20 | 1.00 · 0.9 | 0.16 · 0.0 | 0.20 |
| R2-R006 | 5 | 0.67 · 31.9 | 0.00 · 0.0 | 0.00 |
| R2-R007 | 10 | 0.99 · 37.4 | 0.00 · 0.0 | 0.00 |
| R2-R007 | 20 | 1.00 · 31.1 | 0.00 · 0.0 | 0.00 |
| R2-R007 | 5 | 0.63 · 30.5 | 0.00 · 0.0 | 0.00 |
| R2-R008 | 10 | 1.00 · 18.4 | 0.00 · 0.0 | 0.00 |
| R2-R008 | 20 | 1.00 · 13.8 | 0.00 · 0.0 | 0.00 |
| R2-R008 | 5 | 1.00 · 23.0 | 0.00 · 0.0 | 0.00 |
| R2-R009 | 10 | 0.96 · 8.0 | 0.00 · 0.0 | 0.00 |
| R2-R009 | 20 | 1.00 · 8.3 | 0.00 · 0.0 | 0.00 |
| R2-R009 | 5 | 0.78 · 47.2 | 0.00 · 0.0 | 0.00 |
| R2-R010 | 10 | 1.00 · 17.2 | 0.00 · 0.0 | 0.00 |
| R2-R010 | 20 | 1.00 · 17.2 | 0.00 · 0.0 | 0.00 |
| R2-R010 | 5 | 0.80 · 25.8 | 0.00 · 0.0 | 0.00 |
| R2-R011 | 10 | 0.96 · 50.9 | 0.00 · 0.0 | 0.00 |
| R2-R011 | 20 | 1.00 · 27.4 | 0.00 · 0.0 | 0.00 |
| R2-R011 | 5 | 0.55 · 32.1 | 0.00 · 0.0 | 0.00 |
| R2-R012 | 10 | 1.00 · 29.4 | 0.00 · 0.0 | 0.00 |
| R2-R012 | 20 | 1.00 · 12.0 | 0.00 · 0.0 | 0.00 |
| R2-R012 | 5 | 0.74 · 26.4 | 0.00 · 0.0 | 0.00 |
| R2-R013 | 10 | 0.93 · 19.7 | 0.00 · 0.0 | 0.00 |
| R2-R013 | 20 | 0.99 · 0.6 | 0.00 · 0.0 | 0.00 |
| R2-R013 | 5 | 0.68 · 33.4 | 0.00 · 0.0 | 0.00 |
| R2-R014 | 10 | 1.00 · 21.6 | 0.00 · 0.0 | 0.00 |
| R2-R014 | 20 | 1.00 · 5.4 | 0.00 · 0.0 | 0.00 |
| R2-R014 | 5 | 0.90 · 48.6 | 0.00 · 0.0 | 0.00 |
| R2-R015 | 10 | 1.00 · 12.2 | 0.00 · 0.0 | 0.00 |
| R2-R015 | 20 | 1.00 · 6.1 | 0.00 · 0.0 | 0.00 |
| R2-R015 | 5 | 0.86 · 52.6 | 0.00 · 0.0 | 0.00 |
| R2-R016 | 10 | 0.93 · 6.0 | 0.00 · 0.0 | 0.00 |
| R2-R016 | 20 | 0.99 · 0.5 | 0.33 · 0.0 | 0.40 |
| R2-R016 | 5 | 0.30 · 14.8 | 0.00 · 0.0 | 0.00 |
| R2-R017 | 10 | 0.96 · 23.6 | 0.00 · 0.0 | 0.00 |
| R2-R017 | 20 | 0.99 · 4.1 | 0.00 · 0.0 | 0.00 |
| R2-R017 | 5 | 0.74 · 30.6 | 0.00 · 0.0 | 0.00 |
| R2-R018 | 10 | 1.00 · 52.3 | 0.00 · 0.0 | 0.00 |
| R2-R018 | 20 | 1.00 · 28.5 | 0.00 · 0.0 | 0.00 |
| R2-R018 | 5 | 0.37 · 26.6 | 0.00 · 0.0 | 0.00 |
| R2-R019 | 10 | 0.93 · 38.9 | 0.00 · 0.0 | 0.00 |
| R2-R019 | 20 | 1.00 · 36.6 | 0.00 · 0.0 | 0.00 |
| R2-R019 | 5 | 0.81 · 33.2 | 0.00 · 0.0 | 0.00 |
| R2-R020 | 10 | 1.00 · 0.0 | 0.00 · 0.0 | 0.00 |
| R2-R020 | 20 | 1.00 · 0.0 | 0.36 · 0.0 | 0.40 |
| R2-R020 | 5 | 0.40 · 15.6 | 0.00 · 0.0 | 0.00 |

v2 side check with S-cert (descriptive): overall 0/96 failing families, 0/315 false allows, 149/255 over-escalations (uncertified S in Phase A: 49/96 failing, 0/255 over-escalations; DC-score 0/96, 149/255).

- P1: allow if action_requested = satisfied and actor_identified = satisfied and evidence_uncertainty = satisfied and ownership_authority = satisfied and potential_harm = satisfied and prerequisites_satisfied = satisfied and reversibility = not_satisfied: certified False (1/18 failing calibration families, UCB 0.238)
- P2: allow if action_requested = satisfied and actor_identified = satisfied and evidence_uncertainty = satisfied and ownership_authority = satisfied and potential_harm = not_satisfied and prerequisites_satisfied = satisfied and reversibility = satisfied: certified False (3/15 failing calibration families, UCB 0.440)

## R5: Imperfect perception (arm S, clean labels, k = 10)

Mean catch / mean false invention on the test split at each fact-error rate.

| World | e = 0.0 | e = 0.02 | e = 0.05 | e = 0.1 |
|---|---|---|---|---|
| C_AUTH | 1.00 / 0.000 | 0.98 / 0.008 | 0.94 / 0.014 | 0.89 / 0.034 |
| C_CONFIRM | 1.00 / 0.000 | 0.99 / 0.008 | 0.93 / 0.018 | 0.87 / 0.041 |
| C_OWNER | 1.00 / 0.000 | 0.99 / 0.007 | 0.97 / 0.020 | 0.88 / 0.032 |
| C_REASON | 1.00 / 0.000 | 0.98 / 0.009 | 0.96 / 0.017 | 0.90 / 0.033 |
| C_REFUND | 1.00 / 0.000 | 1.00 / 0.007 | 1.00 / 0.019 | 0.84 / 0.030 |
| C_STATUS | 1.00 / 0.000 | 0.98 / 0.007 | 0.96 / 0.018 | 0.91 / 0.039 |
| H1_LARGE_REFUND | 0.97 / 0.004 | 0.96 / 0.003 | 0.81 / 0.010 | 0.76 / 0.011 |
| H2_PRODUCT | 1.00 / 0.007 | 0.98 / 0.012 | 0.98 / 0.011 | 0.98 / 0.015 |
| H3_REPEAT_CANCEL | 1.00 / 0.003 | 0.95 / 0.008 | 0.95 / 0.010 | 0.90 / 0.020 |
| H4_UPCHARGE | 1.00 / 0.005 | 0.97 / 0.007 | 0.98 / 0.005 | 0.89 / 0.007 |
| H5_CHARGEBACK | 0.00 / 0.000 | 0.00 / 0.000 | 0.00 / 0.000 | 0.00 / 0.000 |
| H6_SMALL_CANCEL_WAIVER | 0.81 / 0.023 | 0.79 / 0.026 | 0.69 / 0.017 | 0.62 / 0.021 |
| H7_PAYPAL_RETURN | 1.00 / 0.023 | 0.88 / 0.023 | 0.94 / 0.026 | 0.92 / 0.029 |
| R2-E001 | 1.00 / 0.000 | 0.94 / 0.000 | 0.85 / 0.001 | 0.86 / 0.012 |
| R2-E002 | 1.00 / 0.000 | 0.98 / 0.000 | 0.96 / 0.001 | 0.90 / 0.003 |
| R2-E003 | 1.00 / 0.000 | 0.96 / 0.000 | 0.96 / 0.002 | 0.94 / 0.003 |
| R2-E004 | 1.00 / 0.000 | 0.98 / 0.000 | 1.00 / 0.000 | 0.84 / 0.002 |
| R2-E005 | 1.00 / 0.000 | 1.00 / 0.003 | 0.91 / 0.004 | 0.91 / 0.008 |
| R2-E006 | 1.00 / 0.000 | 0.97 / 0.000 | 0.93 / 0.001 | 0.92 / 0.001 |
| R2-E007 | 1.00 / 0.000 | 0.95 / 0.001 | 0.98 / 0.004 | 0.87 / 0.009 |
| R2-E008 | 1.00 / 0.000 | 0.99 / 0.000 | 0.96 / 0.001 | 0.93 / 0.001 |
| R2-E009 | 0.93 / 0.004 | 0.92 / 0.002 | 0.88 / 0.012 | 0.72 / 0.004 |
| R2-E010 | 1.00 / 0.000 | 0.99 / 0.001 | 0.92 / 0.002 | 0.89 / 0.002 |
| R2-E011 | 1.00 / 0.009 | 0.99 / 0.000 | 0.93 / 0.012 | 0.78 / 0.012 |
| R2-E012 | 0.97 / 0.015 | 0.90 / 0.017 | 0.88 / 0.011 | 0.83 / 0.009 |
| R2-E013 | 1.00 / 0.000 | 0.98 / 0.000 | 0.96 / 0.001 | 0.87 / 0.004 |
| R2-E014 | 1.00 / 0.006 | 0.94 / 0.008 | 0.96 / 0.014 | 0.93 / 0.013 |
| R2-E015 | 1.00 / 0.000 | 0.98 / 0.001 | 0.95 / 0.003 | 0.91 / 0.009 |
| R2-E016 | 1.00 / 0.000 | 0.99 / 0.001 | 0.95 / 0.000 | 0.90 / 0.004 |
| R2-E017 | 1.00 / 0.000 | 0.98 / 0.001 | 0.95 / 0.001 | 0.89 / 0.001 |
| R2-E018 | 1.00 / 0.007 | 0.99 / 0.011 | 0.88 / 0.007 | 0.73 / 0.035 |
| R2-E019 | 1.00 / 0.000 | 0.99 / 0.002 | 0.94 / 0.005 | 0.90 / 0.005 |
| R2-E020 | 1.00 / 0.001 | 0.99 / 0.003 | 0.95 / 0.004 | 0.91 / 0.006 |
| R2-E021 | 0.99 / 0.001 | 0.98 / 0.001 | 0.94 / 0.005 | 0.90 / 0.006 |
| R2-E022 | 0.93 / 0.007 | 0.95 / 0.012 | 0.86 / 0.004 | 0.82 / 0.018 |
| R2-E023 | 0.93 / 0.013 | 0.94 / 0.005 | 0.88 / 0.005 | 0.83 / 0.017 |
| R2-E024 | 0.97 / 0.018 | 0.94 / 0.012 | 0.90 / 0.011 | 0.84 / 0.017 |
| R2-E025 | 1.00 / 0.009 | 0.98 / 0.013 | 0.96 / 0.012 | 0.92 / 0.030 |
| R2-E026 | 0.97 / 0.021 | 0.95 / 0.016 | 0.95 / 0.020 | 0.83 / 0.015 |
| R2-E027 | 1.00 / 0.004 | 0.97 / 0.004 | 0.95 / 0.002 | 0.87 / 0.006 |
| R2-E028 | 0.82 / 0.003 | 0.95 / 0.006 | 0.91 / 0.013 | 0.89 / 0.013 |
| R2-E029 | 1.00 / 0.000 | 0.99 / 0.000 | 0.96 / 0.002 | 0.88 / 0.002 |
| R2-E030 | 1.00 / 0.009 | 0.92 / 0.008 | 0.93 / 0.016 | 0.88 / 0.023 |

## Reading

All three preregistered checks passed: replication (R1), targeted audits (R3) and certified
exceptions (R4). The two descriptive parts, random rules (R2) and noisy perception (R5), turn
Phase A's anecdotes into curves.

1. **Phase A replicates.**
   - On a fresh generator seed, all 13 worlds landed within one k step of Phase A.
   - The controls behaved the same way.
   - The outcome is again `BENCHMARK_TOO_HARD` (2 of 6 learnable this time). The "too hard"
     verdict is not one dataset's luck.
2. **What is learnable, and when (R2, 114 random rules).**
   - Recovered within 5 examples: 50. Within 10: 69. Within 20: 96.
   - **Rules that need one fact, across all actions, are easy.** Numeric thresholds: 36 of 39
     within 10. Products: 13 of 13 within 5.
   - **Narrow rules are hard.** Scoping a rule to one action or adding a second condition is
     the main cost. One numeric condition on one action: 1 of 10 within 10. Two conditions:
     about a third within 10.
   - **Relaxations are slowest:** 5 of 20 within 10, 15 of 20 within 20.
   - **Why.** The significance gate charges for every extra condition, so narrow rules need
     more evidence.
   - **Rarity was not tested.** The filter kept only rules that change at least 5% of the cases
     in scope (at least 25 training families). How rare an edge case can be and still get
     caught remains open.
3. **Audits must be large, and targeting halves them (R3).**
   - To recover a missing escalation rule from k = 20 to 40 occurrences, random audits needed
     25–100% of allowed cases.
   - Targeted audits (spend half at random, then audit cases matching the most suspicious
     conditions) needed half of random's rate or less in 60 of 119 cells.
   - Targeting did not create false rules: the shuffled control accepted a rule in 0.2% of runs.
   - **Product implication.** Learning a missed risk takes roughly 5–10 audited occurrences.
     Either audit heavily where risk is suspected, or use outcome feedback. A flat 10% audit
     will not find rules.
4. **Certification makes relaxations safe, at the cost of almost all of their gain (R4).**
   - Where a learned exception allowed a case on held-out test families, uncertified S failed
     47% of those families (14,042 of 29,939 across runs).
   - Narrowed, certified exceptions failed 0 of 934.
   - But they rarely passed certification on a 148-family certification split, so they
     retained little: catch at most 0.36, and 0 in most worlds.
   - In the v2 side check, the narrowed rules were close to the planted preferences but still
     failed certification (1 of 18 and 3 of 15 calibration families failing). S-cert fell back
     to DC-score: 0 of 96 failing families, 149 of 255 over-escalations.
   - **Product implication.** Learned relaxations are proposals for a person to approve, not
     automatic changes. Certification with untouched data is what keeps them honest, and it
     needs more held-out families than a small organization has early on.
5. **Perception errors pass through about one to one (R5).**
   - At a 2% fact-error rate, catch stayed around 0.95–0.99, with false invention under 1%.
   - At 10%, catch fell to about 0.85–0.90, with false invention of 1–4%. False invention was
     highest for the removed-clause worlds, where a flipped fact directly flips a decision.
   - The learner does not amplify perception noise, but nothing above it can recover what the
     extractor gets wrong. Extractor accuracy is the ceiling.

**Combined with Phase A.** Policy induction works for escalations once a rule has been seen
about 5–20 times, depending on how narrow it is, and noise and narrowness cost data.

- **It needs targeted audits or outcomes** to see what the gate already allows.
- **It must treat relaxations as human-approved proposals,** certified before they act.
- **Its accuracy is capped by fact extraction.**

None of this has been tested on real organizations, real language or a real extractor; that
is the next step (see [`data-sources.md`](data-sources.md)).

## Provenance and reproduction

Cases `ac018a82fba2a61828591344a0ee5ef1e3d79059fa263203394abc711e618916`; code hashes in [`robustness/manifest.json`](robustness/manifest.json). Full results: [`results/robustness.json`](results/robustness.json).

```bash
python -m hatchway.bench.pi.robust generate   # refuses: written once
python -m hatchway.bench.pi.robust evaluate   # refuses: evaluated once
python -m hatchway.bench.pi.robust report
```
