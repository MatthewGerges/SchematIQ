# SchematIQ

AI-assisted KiCad schematic generation: LLM-driven circuit JSON, deterministic (and optional LLM) placement, and export to KiCad projects you can open in **KiCad**.

---

## Repository layout

| Path | Purpose |
|------|---------|
| **`KiCad10_Cursor/`** | **Current minimal workspace for KiCad 10.** Contains `Example_Schematic/` plus a UI-first runtime copy of `Code/` so you can run SchematIQ from one folder while postponing deep migration work. |
| **`Code/`** | **Main application.** Python backend (`src/`, `scripts/`), FastAPI web API, React+Vite web UI (`webui/`), sample LLM JSON (`data/`), generated KiCad output (`generated/`), tests, and internal docs (`docs/`). **Start here for development.** |
| **`KICAD_Library/`** | KiCad-related library material for this project. The official **`kicad-symbols`** and **`kicad-footprints`** clones are intentionally **not** committed (see root `.gitignore`); clone them locally if you need the full upstream libraries. |
| **`BME280_Rev1/`** | Standalone KiCad/hardware project folder (example or reference design), separate from the generator’s `Code/generated/` tree. |
| **`component_database/`** | Clone official KiCad libraries here (preferred over `KICAD_Library/`); **not committed** (see `.gitignore`). **Symbols:** `git clone https://gitlab.com/kicad/libraries/kicad-symbols.git component_database/kicad-symbols`. **Footprints** (needed for generated `Footprint` fields and `fp-lib-table`): `git clone https://gitlab.com/kicad/libraries/kicad-footprints.git component_database/kicad-footprints`. **3D models** (optional, large; MCad / 3D viewer only): `git clone https://gitlab.com/kicad/libraries/kicad-packages3D.git component_database/kicad-packages3d`. |
| **`scripts/`** (repo root) | Small utilities that operate from the **repository root**, e.g. `build_llm_context.py` (builds the optional LLM context bundle; output file is gitignored). |
| **`chat-ui-localhost-demo/`** | Earlier or auxiliary UI demo; the current product UI lives under **`Code/webui/`**. |
| **`tsci-playground/`** | Experimental tscircuit-related playground. |
| **`tscircuit/`** | External **tscircuit** checkout for experimentation; listed in `.gitignore` and not part of normal SchematIQ commits. |
| **`Rough Data Delete Later/`** | Scratch / non-canonical data (safe to ignore for normal use). |
| **`.vscode/`** | Editor settings (often personal; may be ignored depending on `.gitignore`). |

More detail on the Python modules and generator pipeline: **`Code/README.md`** and **`Code/docs/`**.

---

## New machine: clone and run locally

For KiCad 10 bring-up, use the minimal workspace in `KiCad10_Cursor/` first.

### Prerequisites

- **Python 3** (3.11+ recommended; match what you use on your main dev machine).
- **Node.js** (for the web UI; LTS is fine).
- **KiCad** (8.x is typical for `.kicad_pro` / `.kicad_sch` in this repo). Install from [kicad.org](https://www.kicad.org/).
- A **Google Gemini API key** for chat and LLM features (`GEMINI_API_KEY`).

### 1. Clone

```bash
git clone https://github.com/MatthewGerges/SchematIQ.git
cd SchematIQ
```

### 2. Python environment (`KiCad10_Cursor/Code/` preferred)

For the current minimal migration path, run from **`KiCad10_Cursor/Code/`**.

```bash
cd KiCad10_Cursor/Code
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create **`KiCad10_Cursor/Code/.env`** (never commit secrets):

```bash
# KiCad10_Cursor/Code/.env
GEMINI_API_KEY=your_key_here
```

Optional: change the API port (default **5179**):

```bash
SCHEMATIQ_WEBUI_PORT=5179
```

If you change the API port, update the Vite proxy in `KiCad10_Cursor/Code/webui/vite.config.ts` so `/api` still points at the same host/port.

### 3. Web UI (`KiCad10_Cursor/Code/webui/`)

`node_modules/` is not tracked in git; install dependencies after every clone.

```bash
cd KiCad10_Cursor/Code/webui
npm install
npm run dev
```

- **Frontend:** [http://127.0.0.1:5173](http://127.0.0.1:5173) (Vite dev server).
- **Backend:** run in a **second** terminal from **`KiCad10_Cursor/Code/`** with the venv active:

```bash
cd KiCad10_Cursor/Code
source .venv/bin/activate
python3 scripts/webui_server.py
```

Default API URL: [http://127.0.0.1:5179](http://127.0.0.1:5179) (`/api/health` for a quick check). The Vite dev server **proxies** `/api` to that address.

If `POST /api/chat/start` fails with a `google-genai` import error, from `KiCad10_Cursor/Code/`:

```bash
pip install --upgrade --force-reinstall google-genai
pip install -r requirements.txt
```

### 4. KiCad

Generated projects live under **`Code/generated/<ProjectName>/`**. Open the **`.kicad_pro`** file in KiCad (Schematic Editor / full project). Paths and library tables may assume a standard KiCad install plus any project-local `sym-lib-table` / embedded symbols in that folder.

### 5. CLI / tests (without the web UI)

From **`Code/`** with venv active:

```bash
python tests/test_bme280_generator.py
```

See **`Code/README.md`** for layout, scripts, and troubleshooting.

---

## Remote repository

Primary remote: **https://github.com/MatthewGerges/SchematIQ**

```bash
git remote -v
# origin should point at the SchematIQ URL above
```
