# Judge and strategy comparison (smoke run 2)

| | |
|---|---|
| **Status** | `diagnostic` · `superseded` (by the [targeted shadow experiment](../2026-10-22-targeted-shadow/README.md)) |
| **Date** | 2026-10-22 |
| **Code** | `f08438d` (viewer and replay); oracle `tau2-oracle-1:581044662966` |
| **Decision** | No conclusion. The claims gate blocked every comparison: 5 held-out writes against the minimum of 50, and fewer than 20 per action. A targeted, larger capture was planned. |

## Question

Against the policy verdict, which judge and which strategy would gate writes best? The
strategies were:

- **A:** no gate;
- **B:** plain LLM;
- **C:** Jev;
- **D:** OpenAI Decisions;
- **E:** a fitted single-judge model on Decisions;
- **F:** Jev + Decisions combination.

## Dataset

Smoke run 2: 11 writes, split by task into 6 training writes (2 tasks) and 5 held-out writes
(1 task).

## Result (held-out, 5 writes: 1 should run, 4 should escalate)

| Strategy | False allows | Safe automatic runs |
|---|---|---|
| A no gate | 4 | 1 |
| B plain LLM | 3 | 1 |
| C Jev | 2 | 1 |
| D OpenAI Decisions | 0 | 1 |
| E fitted Decisions model | 1 | 0 |
| F Jev + Decisions | 0 | 0 |

Five writes from one task cannot rank strategies. Full metrics are in
[`metrics.json`](metrics.json); the fitted arms are in [`frozen-arms/`](frozen-arms/).

## Report

- **HTML viewer:** "Hatchway Smoke Viewer" (not published; built from the local build below).
- **Local build:** `runs/smoke2/report/index.html`, sha256
  `1a7eb35ad420239bf915a4a982ab4095cc59f6ef221c6790f363b96bcb1e9b8a`.
- **Store:** `runs/smoke2.db`.
