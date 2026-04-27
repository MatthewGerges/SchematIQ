# KiCad10_Cursor (Minimal UI-First Workspace)

This folder is your new minimal workspace for running SchematIQ with KiCad 10 experiments, without fully migrating symbol/footprint/linking logic yet.

## Included here (minimal runtime only)

- `Code/webui` - React + Vite frontend
- `Code/scripts` - backend entrypoints including `webui_server.py`
- `Code/src` - Python runtime modules used by API/scripts
- `Code/config` and `Code/data` - runtime configuration and project JSON inputs
- `component_database/` - optional; not required for chat (LLM uses KiCad official library names only)
- `Example_Schematic` - your KiCad 10 starter schematic

## Deferred on purpose

- Full symbol-table and footprint-table migration
- LLM placement migration and optimization
- Historical project mass migration/normalization

## Run from this folder

1) Backend API

```bash
cd KiCad10_Cursor/Code
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/webui_server.py
```

2) Frontend UI (second terminal)

```bash
cd KiCad10_Cursor/Code/webui
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

The UI proxies `/api` to `http://127.0.0.1:5179` by default.
