# Clean Local Setup (2 terminals)

## Terminal 1 (backend API)
```bash
cd "/Users/matthewgerges/Documents/AI-PCB/SchematIQ/KiCad10_Cursor/Code"
source .venv/bin/activate
python -m uvicorn scripts.webui_server:app --host 127.0.0.1 --port 5179 --log-level info
```

## Terminal 2 (frontend UI)
```bash
cd "/Users/matthewgerges/Documents/AI-PCB/SchematIQ/KiCad10_Cursor/Code/webui"
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

## Stop/Clean Reset
```bash
pkill -f "uvicorn scripts.webui_server:app|python -m uvicorn scripts.webui_server:app|vite --host 127.0.0.1 --port 5173|npm run dev -- --host 127.0.0.1 --port 5173" || true
```

Open: http://127.0.0.1:5173/
