# PaperOps – The Glove-Proof Industrial Dispatcher

> Press. Speak. Fix.

A maintenance technician presses one button (or a foot pedal) and describes a machine fault by voice. PaperOps understands the report, searches the machine manual, checks spare-part stock and prints a short repair ticket on a thermal printer: safety step first, the right part and its exact shelf location. It also spots recurring faults and recommends preventive maintenance.

Built for the **AMD Developer Hackathon: ACT III** – Track 1 *Intelligent Industry*.

<!-- TODO: screenshot of a printed ticket -->

## Live demo

- App: TODO
- Video: TODO

## How it works

1. **Voice in** – push-to-talk in the browser (space bar or USB foot pedal)
2. **AI on AMD GPUs** – audio goes to **MiMo-V2.6-Flash** on the AMD Token Factory, which calls two tools:
   - `search_manual` – fault codes, causes, repair steps
   - `check_inventory` – part, stock, shelf location
3. **Ticket out** – strict JSON → ESC/POS commands → thermal printer, or the on-screen printer simulator
4. **Early warning** – recurring faults in the ticket history trigger a preventive-maintenance hint

**Resilience:** if a model is unavailable or returns invalid output, PaperOps falls back to `Qwen3.8-27B` → `DeepSeek-V4-Flash`. A replay mode with recorded real runs is available for demos.

## Quick start (Docker)

```bash
cp .env.example .env      # add your RADEON_API_KEY
docker compose up
```

Open http://localhost:8000 – TODO: confirm port.

## Run without Docker

TODO

## Connect a thermal printer (optional)

Any ESC/POS 80 mm printer on your network: set `PRINTER_HOST` in `.env`. Without a printer, the ticket appears in the on-screen simulator (same ESC/POS commands).

## Backup: self-hosted speech-to-text

TODO: how to run Whisper yourself if MiMo is not available.

## Demo data

All data in `data/` is fictional: machine manuals, ERP inventory, test transcripts and a 30-day ticket history.

## License

MIT – see [LICENSE](LICENSE).
