# SchematIQ (application code)

AI-assisted KiCad schematic generation using LLMs and deterministic layout.

## Quick start

```bash
cd Code
source .venv/bin/activate
python tests/test_bme280_generator.py
```

Output: `generated/BME280_Test.kicad_sch` (paths vary by test).

## Layout

- `src/lib/` — Core modules (`kicad_api`, `project_builder`, `schematic_generator`, …)
- `data/` — LLM / project JSON
- `generated/` — Generated KiCad projects
- `docs/` — Documentation
- `tests/` — Tests
- `webui/` — React + Vite frontend (run `npm run dev` here; API from `scripts/webui_server.py`)

See `docs/PROJECT_STATUS.md` for status and next steps.

## Web UI (FastAPI + Vite)

Use the **`Code/`** tree only (repo layout: `SchematIQ/Code/`).

If you **renamed or moved** this folder, delete and recreate `.venv` — old venvs keep a hard-coded path to `python` and break `pip` / imports:

```bash
cd /path/to/SchematIQ/Code
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/webui_server.py
```

In another terminal:

```bash
cd /path/to/SchematIQ/Code/webui
npm install
npm run dev
```

Open `http://127.0.0.1:5173/`. If **`POST /api/chat/start` returns 500** with a `google-genai` / `_compat` error, reinstall the SDK:

```bash
source .venv/bin/activate
pip install --upgrade --force-reinstall google-genai
pip install -r requirements.txt
```

If you see **`No module named fastapi`**, your shell is not using **`Code/.venv`** (or you never ran `pip install -r requirements.txt` there). Use `which python3` after `activate` — it should point inside `Code/.venv/`.
