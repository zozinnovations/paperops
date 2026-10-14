# PaperOps – The Glove-Proof Industrial Dispatcher

> Press. Speak. Fix.

A maintenance technician presses one button (or a foot pedal) and describes a machine fault by voice. PaperOps understands the report, searches the machine manual, checks spare-part stock and prints a short repair ticket on a thermal printer: safety step first, the right part and its exact shelf location. It also spots recurring faults and recommends preventive maintenance.

Built for the **AMD Developer Hackathon: ACT III** – Track 1 *Intelligent Industry*.

**AI: Gemma 4 on AMD GPUs via AMD Token Factory.** Google's open model `Gemma-4-31B-IT` understands every report; it runs on AMD GPUs through the [AMD Token Factory](https://notebooks.amd.com/tokenfactory).

<!-- TODO: screenshot of a printed ticket -->

## Live demo

- App: TODO
- Video: TODO

## How it works

1. **Voice in** – push-to-talk in the browser (hold the button, the space bar or a USB foot pedal)
2. **Speech-to-text** – the recording goes to our backend and is transcribed by **faster-whisper** (`base.en`, int8, CPU, ~0.5 s), primed with the plant's machine names, aliases and error codes. Audio never goes to a third-party cloud.
3. **Gemma 4 on AMD GPUs via AMD Token Factory** – **one** call to **Gemma-4-31B-IT** on the [AMD Token Factory](https://notebooks.amd.com/tokenfactory) turns the transcript into `{machine_id, error_code, cause, part, symptoms}`. The hackathon organizers confirmed officially that running the AI on the Token Factory "perfectly satisfies" the requirement that a substantial part of the workload runs on AMD.
4. **Lookups in code** – machine manual, spare-part stock and shelf location, approved alternatives, 30-day fault history. Repair steps always come from the manual, so the safety step is always first and the model cannot invent parts.
5. **Ticket out** – ESC/POS commands → thermal printer, or the on-screen printer simulator, which renders the very same bytes
6. **Ask back instead of wasting paper** – if no machine or no fault is recognised (a slip of the tongue, small talk, "press three" without a fault), nothing is printed: the screen asks "Which machine?" or "What is wrong with HP-400?", and "Print anyway" is one click away.
7. **Evidence check** – Gemma also returns a short quote from the transcript. The code checks (fuzzily, with spoken numbers normalised) that the quote was really said and that it names the machine and the fault. If not – e.g. Whisper misheard the machine name – the ticket still prints with the safety step, but under a bold **UNCONFIRMED – verify machine on site** banner and "Did you mean …?".
8. **Early warning** – recurring faults (e.g. E-402 on HP-400: 3× in 12 days) trigger a root-cause / preventive-maintenance hint

**Measured** (T01, "Press three is stuck. Error E four oh two. The axis is running hot."): speech-to-text ~2 s + Gemma and ticket ~3–5 s = **~6 s from voice to printed ticket** (more when the Token Factory has a slow moment). All test cases in `data/test_transcripts.json` pass (12 standard cases plus 3 vague/misheard reports that must get the UNCONFIRMED banner or a clarification question) with Gemma, 36/36 over three full runs (`python scripts/bench_cases.py`).

**Resilience:** the app checks `GET /v1/models` at startup and validates every answer. If Gemma fails or returns invalid output, it falls back along `FALLBACK_MODELS`: MiMo-V2.6-Flash → GLM-5.3-Flash → DeepSeek-V4.1-Flash, all on the Token Factory. For the 12 sample recordings, recorded real runs in `replay/` stand by: if the live models fail or take longer than `LLM_BUDGET` (12 s), the app answers from the recording and says so on screen. `REPLAY_MODE=always` gives a fully offline demo, `off` disables replay.

## Quick start (Docker)

```bash
cp .env.example .env      # add your RADEON_API_KEY
docker compose up --build
```

Open http://localhost:8000 (another port on your machine: `HOST_PORT=8002` in `.env`). The build bakes the Whisper model into the image (image ~1.8 GB), so the container never downloads anything at runtime. For a smaller, faster model use `WHISPER_MODEL=base.en`.

## Hosting (demo URL for the judges)

PaperOps needs a long-running process with **2 GB RAM** (faster-whisper keeps its model in memory; the app process uses about 0.4 GB resident, 1.2 GB committed) and **HTTPS** (browsers only allow the microphone on HTTPS). Serverless platforms such as Vercel do not fit. The same Docker image runs on:

| Platform | Config in this repo | Steps |
|---|---|---|
| **Railway** (simplest) | `railway.json` | New project → deploy from the GitHub repo → add variable `RADEON_API_KEY` → Settings → Networking → generate domain (HTTPS included) |
| **Fly.io** | `fly.toml` (2 GB, always on, Frankfurt) | `fly launch --copy-config --no-deploy` → `fly secrets set RADEON_API_KEY=...` → `fly deploy` |
| **Render** | `render.yaml` (plan *standard*, 2 GB) | New → Blueprint → select the repo → enter `RADEON_API_KEY` |

On every platform: set the API key only as a secret in the dashboard, set `PUBLIC_URL` to the HTTPS address (used in the ticket's QR code), and keep one instance always running so judges never hit a cold start. The platform passes `PORT`; the image listens on it and serves `/api/health` for health checks.

**Start page for judges:** no login. "Play the demo report" plays a recorded voice report and runs it through the whole pipeline, and text input plus 12 sample recordings work without a microphone.

### Own server with a domain

Set `DOMAIN` and `PUBLIC_URL` in `.env` and start the bundled Caddy proxy, which gets a certificate automatically:

```bash
docker compose --profile https up -d --build
```

## Run without Docker

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                              # add your RADEON_API_KEY
uvicorn app.main:app --port 8000
```

## Connect a thermal printer (optional)

Any ESC/POS 80 mm printer on your network: set `PRINTER_HOST` (and `PRINTER_PORT`, default 9100) in `.env`. The header shows "Printer: connected". Without a printer, the ticket appears in the on-screen simulator, which interprets the same ESC/POS commands. Tick "Show printer commands" to see them.

## Speech-to-text

`app/stt.py` (`transcribe(audio)`) runs faster-whisper in the container: `WHISPER_MODEL=base.en` (default, ~0.5 s for a 6 s report) or `small.en` (~1.5 s, same ticket accuracy on our 12 samples). The model is loaded and run once at startup, so the first request is fast too. The Token Factory has no speech-to-text model (the gateway rejects audio input), so transcription runs in our backend, and audio never leaves our server.

## Project layout

```
app/        FastAPI backend (main.py), pipeline, LLM fallback chain, STT, ESC/POS, printer, static UI
data/       fictional demo data: manuals, ERP inventory, ticket history, 12 test cases
samples/    spoken versions of the 12 test cases (sample buttons in the UI)
replay/     recorded real model answers for offline demos
scripts/    benchmarks: bench_cases.py (all cases), test_audio.py (voice end-to-end), bench_t01.py
```

## Demo data

All data in `data/` is fictional: machine manuals, ERP inventory, test transcripts and a 30-day ticket history.

## License

MIT – see [LICENSE](LICENSE).
