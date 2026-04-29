#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Lazy-load google-genai so the server starts even when the network is slow.
genai = None  # type: ignore[assignment]
types = None  # type: ignore[assignment]
GoogleSearch = None  # type: ignore[assignment]
Tool = None  # type: ignore[assignment]


def _ensure_genai():
    global genai, types, GoogleSearch, Tool
    if genai is not None:
        return
    try:
        from google import genai as _genai
        from google.genai import types as _types
        from google.genai.types import GoogleSearch as _GS, Tool as _Tool
    except ModuleNotFoundError as e:
        # Common after partial upgrades: missing google.genai._interactions._utils._compat, etc.
        raise HTTPException(
            status_code=500,
            detail=(
                "google-genai failed to import (broken or incomplete install). "
                "From the Code/ directory: source .venv/bin/activate && "
                "pip install --upgrade --force-reinstall google-genai && pip install -r requirements.txt"
            ),
        ) from e
    genai = _genai
    types = _types
    GoogleSearch = _GS
    Tool = _Tool

_ROOT = Path(__file__).resolve().parent.parent
_CODE_ROOT_RESOLVED = _ROOT.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


app = FastAPI(title="SchematIQ Web UI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

load_dotenv(_ROOT / ".env")


@app.get("/", response_class=HTMLResponse)
def root_hint() -> str:
    """This process is JSON API only; the React UI is served by Vite on port 5173."""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>SchematIQ API</title></head>"
        "<body style='font-family:system-ui,sans-serif;max-width:42rem;margin:2rem;line-height:1.5'>"
        "<h1>SchematIQ API</h1>"
        "<p>This port serves <code>/api/*</code> only. Open the web UI at "
        "<a href='http://127.0.0.1:5173/'>http://127.0.0.1:5173/</a> "
        "(run <code>npm run dev</code> in <code>Code/webui</code>).</p>"
        "<p>Health check: <a href='/api/health'>/api/health</a></p>"
        "</body></html>"
    )


MODEL = "gemini-2.5-flash"
_SESSIONS: dict[str, dict[str, Any]] = {}
_SYSTEM_PROMPT_CACHE: str | None = None


class RunRequest(BaseModel):
    action: str  # generate|check|review|repair|validate
    json_path: str
    target: str | None = None  # kicad|tscircuit|both (generate only)
    placement: str | None = None  # "deterministic" | "llm"

class ChatStartRequest(BaseModel):
    json_path: str | None = None


class ChatSendRequest(BaseModel):
    session_id: str
    message: str


class ChatSessionRequest(BaseModel):
    session_id: str


def _extract_json_blocks(text: str) -> list[dict[str, Any]]:
    import re

    pattern = r"```json\s*\n(.*?)```"
    blocks: list[dict[str, Any]] = []
    for match in re.finditer(pattern, text, re.DOTALL):
        try:
            blocks.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass
    return blocks


def _extract_new_component_blocks(text: str) -> list[dict[str, Any]]:
    import re

    pattern = r"```new_component\s*\n(.*?)```"
    blocks: list[dict[str, Any]] = []
    for match in re.finditer(pattern, text, re.DOTALL):
        try:
            blocks.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass
    return blocks


class _ProjectState:
    def __init__(self) -> None:
        self.project_name: str | None = None
        self.description: str = ""
        self.sheets: list[dict[str, Any]] = []
        self.components: list[dict[str, Any]] = []
        self.passives: list[dict[str, Any]] = []
        self.nets: list[dict[str, Any]] = []
        self.new_components: dict[str, Any] = {}
        self.output_json_path: Path | None = None
        self._component_keys: set[tuple[str, str]] = set()
        self._passive_keys: set[tuple[str, str]] = set()
        self._net_keys: set[tuple[str, str]] = set()

    @staticmethod
    def _normalize_component(comp: dict[str, Any]) -> dict[str, Any]:
        """Apply deterministic sanity fixes for common LLM wiring mistakes."""
        part = str(comp.get("part", "")).strip()
        conns = comp.get("connections")
        if not isinstance(conns, list):
            return comp

        part_u = part.upper()
        if part_u.startswith("LED:") or "LED_STANDARD" in part_u:
            part = "Device:LED"
            comp["part"] = part
        if part_u.startswith("TRANSISTOR_NPN_BJT:"):
            part = "Transistor_BJT:" + part.split(":", 1)[1].strip()
            comp["part"] = part
        if part_u.startswith("BUTTON:") or "SW_PUSH" in part_u or "BUTTON_SWITCH" in part_u:
            # Default to 2-pin logical pushbutton unless user explicitly asks for footprint details.
            part = "Switch:SW_Push"
            comp["part"] = part

        # Device:LED has pin 1=K, pin 2=A. If model assigns A->GND and K->signal,
        # the diode is reversed for the common indicator topology; swap the nets.
        if part == "Device:LED":
            k_idx = None
            a_idx = None
            for i, c in enumerate(conns):
                pin_name = str(c.get("pin_name", "")).strip().upper()
                pin_num = str(c.get("pin", "")).strip()
                if pin_num.upper() == "K":
                    c["pin"] = "1"
                    pin_num = "1"
                elif pin_num.upper() == "A":
                    c["pin"] = "2"
                    pin_num = "2"
                if pin_name == "K" or pin_num == "1":
                    k_idx = i
                if pin_name == "A" or pin_num == "2":
                    a_idx = i
            if k_idx is not None and a_idx is not None:
                k_net = str(conns[k_idx].get("net", "")).strip().upper()
                a_net = str(conns[a_idx].get("net", "")).strip().upper()
                if a_net == "GND" and k_net != "GND":
                    conns[k_idx]["net"], conns[a_idx]["net"] = conns[a_idx].get("net"), conns[k_idx].get("net")
                # Heuristic for explicit net naming (e.g. *_ANODE / *_K) with swapped pin numbers.
                if ("ANODE" in k_net or k_net.endswith("_A")) and ("_K" in a_net or "CATHODE" in a_net):
                    conns[k_idx]["net"], conns[a_idx]["net"] = conns[a_idx].get("net"), conns[k_idx].get("net")

            # Canonicalize LED pin metadata for downstream mapping-by-name.
            for c in conns:
                pin_num = str(c.get("pin", "")).strip()
                if pin_num == "1":
                    c["pin_name"] = "K"
                elif pin_num == "2":
                    c["pin_name"] = "A"

        if part == "Switch:SW_Push":
            # Collapse 4-pin tactile-style descriptions into two electrical terminals.
            pnet: dict[str, str] = {}
            for c in conns:
                p = str(c.get("pin", "")).strip()
                n = str(c.get("net", "")).strip()
                if p and n:
                    pnet[p] = n

            n1 = pnet.get("1") or pnet.get("2")
            n2 = pnet.get("3") or pnet.get("4")

            # Fallback: first two distinct nets in order of appearance.
            if not n1 or not n2 or n1 == n2:
                distinct: list[str] = []
                for c in conns:
                    n = str(c.get("net", "")).strip()
                    if n and n not in distinct:
                        distinct.append(n)
                if len(distinct) >= 2:
                    n1, n2 = distinct[0], distinct[1]

            if n1 and n2:
                comp["connections"] = [
                    {"pin": "1", "pin_name": "1", "net": n1},
                    {"pin": "2", "pin_name": "2", "net": n2},
                ]
        return comp

    def ingest(self, data: dict[str, Any]) -> str | None:
        if "project_name" in data and "sheets" in data:
            self.project_name = data.get("project_name")
            self.description = data.get("description", "")
            self.sheets = list(data.get("sheets", []))
            return "sheets"

        if "sheet_design" in data:
            sheet = data["sheet_design"]
            if not self.sheets:
                self.sheets = [{"name": sheet, "file": f"{sheet}.kicad_sch", "page": 1}]
            if not self.project_name:
                self.project_name = sheet

            # When a sheet is redesigned, clear ALL old items for that sheet
            # first.  This prevents stale passives/components from a previous
            # design (e.g. buck converter R1/L1) lingering after a redesign
            # (e.g. LDO with only C1/C2).
            self.components = [
                c for c in self.components
                if c.get("sheet", "") != sheet
            ]
            self._component_keys = {
                k for k in self._component_keys if k[0] != sheet
            }
            self.passives = [
                p for p in self.passives
                if p.get("sheet", "") != sheet
            ]
            self._passive_keys = {
                k for k in self._passive_keys if k[0] != sheet
            }
            self.nets = [
                n for n in self.nets
                if n.get("sheet", "") != sheet
            ]
            self._net_keys = {
                k for k in self._net_keys if k[0] != sheet
            }

            for comp in data.get("components", []):
                comp = self._normalize_component(comp)
                key = (comp.get("sheet", sheet), comp.get("ref"))
                self._component_keys.add(key)
                self.components.append(comp)
            for p in data.get("passives", []):
                key = (p.get("sheet", sheet), p.get("ref"))
                self._passive_keys.add(key)
                self.passives.append(p)
            for n in data.get("nets", []):
                key = (n.get("sheet", sheet), n.get("name"))
                self._net_keys.add(key)
                self.nets.append(n)
            return f"sheet:{sheet}"

        if "cross_sheet_nets" in data:
            for n in data["cross_sheet_nets"]:
                key = (n.get("sheet", ""), n.get("name"))
                if key in self._net_keys:
                    continue
                self._net_keys.add(key)
                self.nets.append(n)
            return "cross_sheet_nets"
        return None

    def ingest_new_component(self, data: dict[str, Any]) -> None:
        name = data.get("name", f"unnamed_{len(self.new_components)+1}")
        self.new_components[name] = data

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name or "Untitled",
            "description": self.description or "",
            "sheets": self.sheets,
            "components": self.components,
            "passives": self.passives,
            "nets": self.nets,
        }


def _build_output_path(state: _ProjectState) -> Path:
    data_dir = _ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    import re

    base_name = state.project_name or "llm_output"
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", base_name).strip("_") or "llm_output"
    candidate = data_dir / f"llm_output_{slug}.json"
    if not candidate.exists():
        return candidate
    idx = 1
    while True:
        candidate = data_dir / f"llm_output_{slug}_{idx}.json"
        if not candidate.exists():
            return candidate
        idx += 1


def _save_state(state: _ProjectState) -> Path:
    out = state.output_json_path or _build_output_path(state)
    state.output_json_path = out
    with open(out, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2)
        f.write("\n")
    return out


def _recent_project_jsons(limit: int = 5) -> list[Path]:
    data_dir = _ROOT / "data"
    if not data_dir.is_dir():
        return []
    paths = list(data_dir.glob("llm_output*.json"))
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return paths[:limit]


def _unresolved_symbol_lines(design: dict[str, Any]) -> list[str]:
    """Return human-readable unresolved symbol lines under strict mode."""
    try:
        from src.lib.symbol_preflight import find_unresolved_components
    except Exception:
        return []
    unresolved = find_unresolved_components(design)
    if not unresolved:
        return []
    lines = [f"Strict symbol mode: {len(unresolved)} unresolved symbol(s)."]
    for u in unresolved[:12]:
        lines.append(
            f"- {u.get('ref', '?')}: {u.get('part', '')} (lookup: {u.get('lookup', '')})"
        )
    if len(unresolved) > 12:
        lines.append(f"- ... and {len(unresolved) - 12} more")
    return lines


def _system_prompt() -> str:
    """Reuse the CLI playground prompt; cache so repeated chat sessions skip re-import."""
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is not None:
        return _SYSTEM_PROMPT_CACHE
    from scripts.prompt_playground import SYSTEM_PROMPT

    _SYSTEM_PROMPT_CACHE = SYSTEM_PROMPT
    return _SYSTEM_PROMPT_CACHE


def _resolve_json_path(raw: str) -> Path:
    """Resolve *raw* to an existing path. Relative paths must stay under this ``Code/`` tree."""
    p = Path(raw).expanduser()
    if p.is_absolute():
        rp = p.resolve()
    else:
        rp = (_ROOT / p).resolve()
        try:
            rp.relative_to(_CODE_ROOT_RESOLVED)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=(
                    "json_path escapes the Code directory (e.g. ../… is not allowed). "
                    "Use paths under Code/data such as data/llm_output_MyBoard.json."
                ),
            ) from e
    if not rp.exists():
        raise HTTPException(status_code=404, detail=f"json_path not found: {rp}")
    return rp


@app.get("/api/projects")
def list_projects() -> dict[str, Any]:
    data_dir = _ROOT / "data"
    paths = sorted(data_dir.glob("llm_output*.json"))
    return {"projects": [str(p) for p in paths]}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"ok": "true"}


@app.post("/api/chat/start")
def start_chat(req: ChatStartRequest) -> dict[str, Any]:
    _ensure_genai()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set in Code/.env")
    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=_system_prompt(),
            tools=[Tool(google_search=GoogleSearch())],
        ),
    )
    state = _ProjectState()
    if req.json_path:
        p = _resolve_json_path(req.json_path)
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        state.project_name = data.get("project_name")
        state.description = data.get("description", "")
        state.sheets = list(data.get("sheets", []))
        state.components = list(data.get("components", []))
        state.passives = list(data.get("passives", []))
        state.nets = list(data.get("nets", []))
        state.output_json_path = p
    sid = str(uuid.uuid4())
    # Keep the client alive for the full session; otherwise the underlying
    # HTTP client may be closed once this function returns.
    _SESSIONS[sid] = {"client": client, "chat": chat, "state": state}
    if req.json_path:
        # Prime model with existing board so the next user prompt naturally
        # continues edits instead of starting from scratch.
        seed_payload = json.dumps(state.to_dict(), indent=2)
        seed_prompt = (
            "Continue editing this existing project JSON. Treat it as the current state.\n"
            "When proposing changes, output JSON blocks that can be merged into this state.\n\n"
            f"{seed_payload}"
        )
        chat.send_message(seed_prompt)
        opener = chat.send_message(
            "I loaded an existing board. Ask me what should be changed and I will continue from it."
        )
    else:
        recent = _recent_project_jsons(limit=4)
        if recent:
            recent_list = "\n".join(f"- {p.name}" for p in recent)
            opener = chat.send_message(
                "Start by asking whether I want to continue from an existing project or start new.\n"
                "If I want to continue, confirm which one from this list by filename:\n"
                f"{recent_list}\n"
                "Do not assume; ask first."
            )
        else:
            opener = chat.send_message("Hello, I'd like to design a board.")
    text = opener.text or ""
    captured: list[str] = []
    for b in _extract_json_blocks(text):
        r = state.ingest(b)
        if r:
            captured.append(r)
    for b in _extract_new_component_blocks(text):
        state.ingest_new_component(b)
        captured.append(f"new_component:{b.get('name', 'unknown')}")
    return {
        "session_id": sid,
        "assistant": text,
        "captured": captured,
        "state": state.to_dict(),
        "json_path": str(state.output_json_path) if state.output_json_path else None,
    }


@app.post("/api/chat/send")
def send_chat(req: ChatSendRequest) -> dict[str, Any]:
    sess = _SESSIONS.get(req.session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="chat session not found")
    chat = sess["chat"]
    state: _ProjectState = sess["state"]
    try:
        response = chat.send_message(req.message)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Gemini chat failed: {e}") from e
    text = response.text or ""
    captured: list[str] = []
    for b in _extract_json_blocks(text):
        r = state.ingest(b)
        if r:
            captured.append(r)
    for b in _extract_new_component_blocks(text):
        state.ingest_new_component(b)
        captured.append(f"new_component:{b.get('name', 'unknown')}")

    unresolved_lines = _unresolved_symbol_lines(state.to_dict())
    if unresolved_lines:
        lines = ["", "---", "**Strict symbol mode:** generation is blocked.", *unresolved_lines]
        text = text + "\n" + "\n".join(lines)

    return {"assistant": text, "captured": captured, "state": state.to_dict()}


@app.post("/api/chat/save")
def save_chat(req: ChatSessionRequest) -> dict[str, Any]:
    sess = _SESSIONS.get(req.session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="chat session not found")
    state: _ProjectState = sess["state"]
    path = _save_state(state)
    return {"json_path": str(path), "state": state.to_dict()}


@app.post("/api/run")
def run_action(req: RunRequest) -> dict[str, Any]:
    json_path = _resolve_json_path(req.json_path)
    # Hard gate: no generation/review/check with unresolved symbol names.
    try:
        with open(json_path, encoding="utf-8") as f:
            design = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed reading JSON: {e}") from e

    action = req.action.strip().lower()
    if action not in ("generate", "check", "review", "repair", "validate"):
        raise HTTPException(status_code=400, detail="invalid action")

    if action in ("generate", "check", "review", "validate"):
        lines = _unresolved_symbol_lines(design)
        if lines:
            return {
                "command": [],
                "cwd": str(_ROOT),
                "exit_code": 2,
                "stdout": "",
                "stderr": "Symbol resolution failed.\n" + "\n".join(lines),
                "kicad_pro_path": None,
            }

    if action == "generate":
        target = (req.target or "both").strip().lower()
        if target not in ("kicad", "tscircuit", "both"):
            raise HTTPException(status_code=400, detail="invalid target")
        cmd = [
            sys.executable,
            "scripts/generate_from_llm.py",
            "--repair",
            "--validate",
            *(
                ["--llm-place"]
                if (req.placement or "").strip().lower() in ("llm", "llm_place", "llm-place")
                else []
            ),
            "--target",
            target,
            str(json_path),
        ]
    elif action == "check":
        # use playground check logic by calling it as a module isn't exposed; call generate_from_llm review+validate
        cmd = [
            sys.executable,
            "scripts/generate_from_llm.py",
            "--repair",
            "--review",
            "--validate",
            "--target",
            "kicad",
            str(json_path),
        ]
    elif action == "review":
        cmd = [sys.executable, "scripts/review_llm_json.py", str(json_path), "--fail-on", "none"]
    elif action == "repair":
        cmd = [sys.executable, "scripts/generate_from_llm.py", "--repair", "--target", "kicad", str(json_path)]
    else:  # validate
        cmd = [sys.executable, "scripts/generate_from_llm.py", "--validate", "--target", "kicad", str(json_path)]

    proc = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True)
    kicad_pro_path = None
    if action == "generate":
        m = re.search(r'(/[^\s\'"]+\.kicad_pro)\b', f"{proc.stdout}\n{proc.stderr}")
        if m:
            kicad_pro_path = m.group(1)
    return {
        "command": cmd,
        "cwd": str(_ROOT),
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "kicad_pro_path": kicad_pro_path,
    }


def main() -> int:
    # Lazy import so requirements are only needed when running the server
    import uvicorn

    port = int(os.getenv("SCHEMATIQ_WEBUI_PORT") or os.getenv("CHIPCHAT_WEBUI_PORT", "5179"))
    print(f"SchematIQ API listening on http://127.0.0.1:{port}  (health: /api/health)", flush=True)
    uvicorn.run("scripts.webui_server:app", host="127.0.0.1", port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

