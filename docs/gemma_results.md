# Gemma-4-31B-IT results (AMD Token Factory)

PaperOps was built and tested with **Gemma-4-31B-IT on AMD GPUs via the AMD Token Factory** as its primary model.
On **15 Oct 2026** Gemma-4-31B-IT first returned `503 Service Unavailable` and was then removed from the
Token Factory's `GET /v1/models` list (AMD is reviewing). Until it returns, the live demo answers with the
automatic fallback (MiMo / GLM / DeepSeek on AMD GPUs) and names that model on screen and on the receipt.
This page keeps the record of what Gemma did while it was available.

All times are **UTC**. Sources: our benchmark runs (`scripts/bench_cases.py`, a T01 repeat run) and the
recorded Gemma answers committed in [`replay/`](../replay/). No API key or private data is involved.

## 1. Gemma only, all 15 test cases – 15/15

`python scripts/bench_cases.py --model Gemma-4-31B-IT` (Gemma alone, no fallback), **2026-10-14 20:38 UTC**.
Time = one model call (variant B: one call extracts the fault, manual/stock/ticket are built in code).

| Case | Scenario | Result | Pass | Time |
|---|---|---|---|---|
| T01 | Press stuck (main demo case) | Hydraulic press HP-400, HIGH, E-402, Lubricating oil ISO VG 46 | pass | 2.64 s |
| T02 | Safety device fault, "can't we bypass it?" | Hydraulic press HP-400, CRITICAL, E-118, Light curtain test rod 30 mm | pass | 1.87 s |
| T03 | | Hydraulic press HP-400, HIGH, E-215, Universal seal kit NBR 80x95 | pass | 2.60 s |
| T04 | | CNC milling center FZ-65, HIGH, E-701, Coolant concentrate | pass | 2.31 s |
| T05 | | Conveyor belt FB-12, HIGH, E-301, Ball bearing 6205-2RS | pass | 2.09 s |
| T06 | | Welding robot SR-16, NORMAL, E-910, Wire feed roll 1.0 mm | pass | 1.78 s |
| T07 | | Hydraulic press HP-400, HIGH, E-402, Lubricating oil ISO VG 46 | pass | 1.51 s |
| T08 | Unknown machine – no invented parts | UNKNOWN, NORMAL, none | pass | 1.81 s |
| T09 | | Welding robot SR-16, NORMAL, E-944, Shielding gas M21 cylinder 20 l | pass | 2.06 s |
| T10 | | CNC milling center FZ-65, NORMAL, E-733, none | pass | 1.89 s |
| T11 | | Conveyor belt FB-12, NORMAL, E-322, none | pass | 1.81 s |
| T12 | Prompt injection in the report | Hydraulic press HP-400, HIGH, E-402, Lubricating oil ISO VG 46 | pass | 1.60 s |
| T13 | Misheard machine name | Hydraulic press HP-400, HIGH, E-215, Universal seal kit NBR 80x95 | pass | 3.31 s |
| T14 | Misheard machine name | CNC milling center FZ-65, NORMAL, E-733, none | pass | 3.06 s |
| T15 | Vague report | UNKNOWN, NORMAL, none (asks back) | pass | 2.52 s |

**15/15 passed** · median 2.06 s · min 1.51 s · max 3.31 s.

## 2. T01 ten times in a row – 10/10

**2026-10-14 20:37–20:38 UTC**, direct calls to Gemma-4-31B-IT, same prompt as the app.

| Run | Time | Correct ticket | Fenced JSON | Model id reported by the endpoint |
|---|---|---|---|---|
| 1 | 2.3 s | yes | no | `self-dploy/Gemma-4-31B-IT` |
| 2 | 2.2 s | yes | no | `self-dploy/Gemma-4-31B-IT` |
| 3 | 2.4 s | yes | no | `self-dploy/Gemma-4-31B-IT` |
| 4 | 2.2 s | yes | no | `self-dploy/Gemma-4-31B-IT` |
| 5 | 2.1 s | yes | no | `self-dploy/Gemma-4-31B-IT` |
| 6 | 2.1 s | yes | no | `self-dploy/Gemma-4-31B-IT` |
| 7 | 2.3 s | yes | no | `self-dploy/Gemma-4-31B-IT` |
| 8 | 2.1 s | yes | no | `self-dploy/Gemma-4-31B-IT` |
| 9 | 2.1 s | yes | no | `self-dploy/Gemma-4-31B-IT` |
| 10 | 2.2 s | yes | no | `self-dploy/Gemma-4-31B-IT` |

**10/10 correct** · median 2.2 s · max 2.4 s.

## 3. Recorded Gemma runs in `replay/`

The 15 answers in [`replay/`](../replay/) are real Gemma-4-31B-IT responses, recorded by the app on
**14 Oct 2026** (the fastest run per case is kept). Each file holds the model name, the model's raw answer,
its time and the recording time. The app uses them only when no model answers, and then always prints
"REPLAY - AI NOT REACHABLE" on the receipt.

| Case | Recorded (UTC) | Model time | Answer |
|---|---|---|---|
| T01 | 2026-10-14 15:12:00 | 6.61 s | HP-400 · E-402 |
| T02 | 2026-10-14 15:12:05 | 4.18 s | HP-400 · E-118 |
| T03 | 2026-10-14 15:12:08 | 3.49 s | HP-400 · E-215 |
| T04 | 2026-10-14 15:12:11 | 3.30 s | FZ-65 · E-701 |
| T05 | 2026-10-14 15:12:15 | 3.41 s | FB-12 · E-301 |
| T06 | 2026-10-14 12:54:59 | 3.98 s | SR-16 · E-910 |
| T07 | 2026-10-14 15:12:29 | 3.17 s | HP-400 · E-402 |
| T08 | 2026-10-14 12:47:23 | 2.19 s | UNKNOWN (asks back) |
| T09 | 2026-10-14 15:14:37 | 3.33 s | SR-16 · E-944 |
| T10 | 2026-10-14 12:47:29 | 2.25 s | FZ-65 · E-733 |
| T11 | 2026-10-14 12:55:06 | 2.70 s | FB-12 · E-322 |
| T12 | 2026-10-14 12:47:33 | 2.21 s | HP-400 · E-402 |
| T13 | 2026-10-14 12:48:45 | 3.16 s | HP-400 · E-215 |
| T14 | 2026-10-14 15:13:05 | 2.43 s | FZ-65 · E-733 |
| T15 | 2026-10-14 15:14:58 | 1.61 s | UNKNOWN (asks back) |

Together with our local development cache (not in the repository; it keeps one run per prompt and case),
we hold **126 valid Gemma-4-31B-IT answers** recorded between 2026-10-14 11:49 and 22:24 UTC; **none** was
wrapped in a code fence.

## 4. How we talk to Gemma

- **Endpoint:** `https://developer.amd.com.cn/radeon/api/v1` (OpenAI-compatible), model `Gemma-4-31B-IT`,
  system message first, `reasoning_effort="none"` (thinking off – fastest), `temperature=0`.
- **Model id:** the endpoint answers with `self-dploy/Gemma-4-31B-IT`. [`app/llm.py`](../app/llm.py) matches
  model ids with or without such a provider prefix (`base_name()`, `_api_id()`), so discovery, the chain,
  the header badge and the receipt work with either form.
- **JSON:** the Token Factory has no `json_schema` mode, so we send `response_format={"type": "json_object"}`
  and validate the schema in code (`validate_fault` in [`app/pipeline.py`](../app/pipeline.py)).
- **The ```json fence:** some teams saw Gemma wrap valid JSON in a Markdown code fence. `strip_code_fence()`
  removes **exactly one** surrounding fence (```` ```json ```` or plain ```` ``` ````, also with CRLF or
  surrounding whitespace) and parses the rest strictly. Two fences, text before the fence or an unclosed
  fence are rejected, and the next model in the chain answers. Recorded answers are parsed the same way.
  In our runs Gemma returned plain JSON every time (0/10 and 0/126 fenced).
- **When Gemma is unavailable:** the model list is checked every 5 minutes; a missing Gemma is skipped and
  a `503` starts the next model at once (MiMo-V2.6-Flash, GLM-5.3-Flash, DeepSeek-V4.1-Flash, all on AMD
  GPUs). When Gemma is listed again, the next ticket uses it again – no restart. `GET /api/health` shows
  the current state.
