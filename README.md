# PaperOps – The Glove-Proof Industrial Dispatcher

> Press. Speak. Fix.

A maintenance technician presses one button (or a foot pedal) and describes a machine fault by voice. PaperOps understands the report, searches the machine manual, checks spare-part stock and prints a short repair ticket on a thermal printer: safety step first, the right part and its exact shelf location. It also spots recurring faults and recommends preventive maintenance.

Built for the **AMD Developer Hackathon: ACT III** – Track 1 *Intelligent Industry*.

<!-- TODO: screenshot of a printed ticket -->

## Live demo

- App: TODO
- Video: TODO

## How it works

1. **Voice in** – push-to-talk in the browser (hold the button, the space bar or a USB foot pedal)
2. **Speech-to-text** – the recording goes to our backend and is transcribed by **faster-whisper** (`small.en`, int8, CPU), primed with the plant's machine names, aliases and error codes. Audio never goes to a third-party cloud.
3. **AI on AMD GPUs** – **one** call to **MiMo-V2.6-Flash** on the AMD Token Factory turns the transcript into `{machine_id, error_code, cause, part, symptoms}`
4. **Lookups in code** – machine manual, spare-part stock and shelf location, approved alternatives, 30-day fault history. Repair steps always come from the manual, so the safety step is always first and the model cannot invent parts.
5. **Ticket out** – ESC/POS commands → thermal printer, or the on-screen printer simulator, which renders the very same bytes
6. **Early warning** – recurring faults (e.g. E-402 on HP-400: 3× in 12 days) trigger a root-cause / preventive-maintenance hint

**Measured** (T01, "Press three is stuck. Error E four oh two. The axis is running hot."): speech-to-text ~2.2 s + AI and ticket ~4.4 s = **~6.5 s from voice to printed ticket**. All 12 test cases in `data/test_transcripts.json` pass (`python scripts/bench_cases.py`).

**Resilience:** the app checks `GET /v1/models` at startup and validates every answer. If a model fails or returns invalid output, it falls back along `FALLBACK_MODELS`. Every successful answer is cached; with `REPLAY_MODE=fallback` (default) recorded real runs from `replay/` are used only if every model fails, `REPLAY_MODE=always` gives a fully offline demo.

## Quick start (Docker)

```bash
cp .env.example .env      # add your RADEON_API_KEY
docker compose up --build
```

Open http://localhost:8000. The first build downloads the Whisper model into the image (~500 MB). For a smaller, faster image use `WHISPER_MODEL=base.en` in `.env`.

### Hosted with HTTPS

Browsers only allow the microphone on HTTPS (or `localhost`). On a server with a domain pointing to it, set `DOMAIN` and `PUBLIC_URL` in `.env` and start the bundled Caddy proxy, which gets a certificate automatically:

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

## Speech-to-text options

`app/stt.py` is the single entry point (`transcribe(audio)`):

| `STT_BACKEND` | What runs | Notes |
|---|---|---|
| `local` (default) | faster-whisper in the container | `WHISPER_MODEL=small.en` (accurate, ~2 s) or `base.en` (~0.7 s) |
| `tokenfactory` | Whisper on the AMD Token Factory | once AMD offers an audio model; set `TF_STT_MODEL` |

MiMo-V2.6-Flash is documented with audio input, but the Token Factory gateway currently rejects audio content (tested 14 Oct 2026), so speech-to-text runs in our backend.

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
