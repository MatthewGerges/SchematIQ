# ChipChat Web UI (local)

This is a small local web app (Vite + React) that calls a lightweight local API server to:

- pick a `data/llm_output*.json`
- run **Generate** (KiCad/tscircuit)
- run **Check** (symbols + electrical review)
- use a **chatbot panel** (Gemini-backed) as a web replacement for `prompt_playground.py`
- show logs + report paths

## Run

In one terminal:

```bash
cd ChipChat_Project
source .venv/bin/activate
pip install -r requirements.txt
python scripts/webui_server.py
```

In another terminal:

```bash
cd ChipChat_Project/webui
npm install
npm run dev
```

Open the URL printed by Vite.

## Deploy frontend to Vercel (Phase 1)

Set `VITE_API_BASE_URL` to your hosted backend URL.

Example:

```bash
VITE_API_BASE_URL=https://api.your-domain.com npm run build
```

In Vercel project settings for this frontend:

- Root Directory: `Code/webui`
- Build Command: `npm run build`
- Output Directory: `dist`
- Environment Variable: `VITE_API_BASE_URL=https://api.your-domain.com`

## Common error

If the page shows `500` / `ECONNREFUSED 127.0.0.1:5179`, the API server is not running.
Start `python scripts/webui_server.py` first, then refresh the web page.

