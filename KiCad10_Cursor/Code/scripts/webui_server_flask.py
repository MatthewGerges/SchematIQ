#!/usr/bin/env python3
"""Flask-based SchematIQ Web UI API server.

Replaces FastAPI/pydantic/uvicorn to avoid Python 3.13 compatibility issues.
google-genai is imported in a background thread so the server starts instantly.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from dotenv import load_dotenv

# ── Path setup ──────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
_CODE_ROOT_RESOLVED = _ROOT.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

load_dotenv(_ROOT / ".env")

# ── Flask app ───────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

# ── Logging ─────────────────────────────────────────────────────────────────
_LOG = logging.getLogger("schematiq.webui")

def _configure_logging():
    lvl_name = os.getenv("SCHEMATIQ_LOG_LEVEL", "INFO").upper()
    lvl = getattr(logging, lvl_name, logging.INFO)
    if not _LOG.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(levelname)s [schematiq] %(message)s"))
        _LOG.addHandler(h)
    _LOG.setLevel(lvl)
    _LOG.propagate = False

_configure_logging()

# ── google-genai: background import ────────────────────────────────────────
MODEL = "gemini-2.5-flash"
_SESSIONS: dict[str, dict[str, Any]] = {}
_SYSTEM_PROMPT_CACHE: str | None = None
_SESSION_ACTIVITY: dict[str, dict[str, Any]] = {}

genai = None
types = None
GoogleSearch = None
Tool = None
_GENAI_READY = threading.Event()
_GENAI_ERROR: str | None = None
_GENAI_CLIENT: Any = None


def _bg_import_genai():
    """Import google-genai in background thread so server starts instantly."""
    global genai, types, GoogleSearch, Tool, _GENAI_ERROR, _GENAI_CLIENT
    _LOG.info("[bg] importing google-genai …")
    t0 = time.perf_counter()
    try:
        from google import genai as _g
        from google.genai import types as _t
        from google.genai.types import GoogleSearch as _GS, Tool as _Tool
        genai = _g
        types = _t
        GoogleSearch = _GS
        Tool = _Tool
        _LOG.info("[bg] google-genai imported in %.1fs", time.perf_counter() - t0)
        # Also create the client
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            t1 = time.perf_counter()
            _GENAI_CLIENT = genai.Client(api_key=api_key)
            _LOG.info("[bg] Gemini client ready in %.1fs", time.perf_counter() - t1)
    except Exception as e:
        _GENAI_ERROR = str(e)
        _LOG.error("[bg] google-genai import FAILED: %s", e)
    finally:
        _GENAI_READY.set()

# Start background import immediately
_import_thread = threading.Thread(target=_bg_import_genai, daemon=True)
_import_thread.start()


def _wait_genai(timeout: float = 180):
    """Block until google-genai is ready, or raise.

    Render free instances can cold-start slowly; keep this bounded so the UI
    doesn't hang indefinitely. Increase via SCHEMATIQ_GENAI_IMPORT_TIMEOUT_S.
    """
    try:
        timeout = float(os.getenv("SCHEMATIQ_GENAI_IMPORT_TIMEOUT_S", str(timeout)) or timeout)
    except Exception:
        timeout = timeout
    if not _GENAI_READY.wait(timeout=timeout):
        abort(503, description=f"google-genai is still loading after {int(timeout)}s. Please retry.")
    if _GENAI_ERROR:
        abort(500, description=f"google-genai failed to import: {_GENAI_ERROR}")


def _get_client():
    global _GENAI_CLIENT
    _wait_genai()
    if _GENAI_CLIENT:
        return _GENAI_CLIENT
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        abort(500, description="GEMINI_API_KEY not set in Code/.env")
    _GENAI_CLIENT = genai.Client(api_key=api_key)
    return _GENAI_CLIENT


def _create_gemini_chat(client) -> Any:
    """Create a server-side Gemini chat (network-bound). Caller has waited for GenAI imports."""
    t0 = time.perf_counter()
    try:
        chat = client.chats.create(
            model=MODEL,
            config=types.GenerateContentConfig(system_instruction=_system_prompt()),
        )
    except Exception as e:
        _LOG.error("chats.create FAILED: %s", e)
        raise
    _LOG.info("chats.create ok in %.2fs", time.perf_counter() - t0)
    return chat


def _ensure_gemini_chat(sess: dict[str, Any]) -> Any:
    """Lazily create Gemini chat / wait for imports on first use (new-session path)."""
    chat = sess.get("chat")
    if chat is not None:
        return chat
    # Phase 1: wait for imports (may be slow on cold start)
    sid = str(sess.get("sid") or "")  # optional; used only for activity if present
    if sid:
        _set_activity(sid, "preparing_gemini", "Importing google-genai…")
    t0 = time.perf_counter()
    _wait_genai()
    _LOG.info("[ensure_chat] genai ready in %.2fs", time.perf_counter() - t0)

    # Phase 2: client init (fast unless key missing / transport issues)
    if sid:
        _set_activity(sid, "preparing_gemini", "Creating Gemini client…")
    t1 = time.perf_counter()
    client = _get_client()
    _LOG.info("[ensure_chat] client ready in %.2fs", time.perf_counter() - t1)

    # Phase 3: chat creation (network-bound)
    if sid:
        _set_activity(sid, "preparing_gemini", "Creating Gemini chat…")
    sess["chat"] = _create_gemini_chat(client)
    return sess["chat"]


# ── Helper: error JSON ─────────────────────────────────────────────────────
def _err(status: int, detail: str):
    return jsonify({"detail": detail}), status


# ── Business logic: lazy-import wrappers ────────────────────────────────────
# Importing webui_server at module level triggers FastAPI → pydantic, which
# takes minutes on Python 3.13.  These thin wrappers defer the import to first
# use (which happens inside request handlers, long after the server is up).

_ws_cache = None

def _ws():
    global _ws_cache
    if _ws_cache is None:
        import scripts.webui_server as _m
        _ws_cache = _m
    return _ws_cache

def _extract_json_blocks(t):          return _ws()._extract_json_blocks(t)
def _extract_new_component_blocks(t): return _ws()._extract_new_component_blocks(t)
def _strip_machine_blocks(t):         return _ws()._strip_machine_blocks(t)
def _concise_user_text(t, **kw):      return _ws()._concise_user_text(t, **kw)
def _env_flag(n, **kw):               return _ws()._env_flag(n, **kw)
def _ProjectState():                  return _ws()._ProjectState()
def _save_state(s):                   return _ws()._save_state(s)
def _recent_project_jsons(**kw):      return _ws()._recent_project_jsons(**kw)
def _try_load_project_from_message(s, m): return _ws()._try_load_project_from_message(s, m)
def _extract_goal_hint(m):            return _ws()._extract_goal_hint(m)
def _unresolved_symbol_lines(d):      return _ws()._unresolved_symbol_lines(d)
def _autofix_unresolved_symbols(s):   return _ws()._autofix_unresolved_symbols(s)
def _autofix_unresolved_symbols_in_design(d): return _ws()._autofix_unresolved_symbols_in_design(d)
def _symbol_candidates_payload(**kw): return _ws()._symbol_candidates_payload(**kw)
def _batch_symbol_candidates_payload(p, **kw): return _ws()._batch_symbol_candidates_payload(p, **kw)
def _tool_search_symbols(**kw):       return _ws()._tool_search_symbols(**kw)


def _system_prompt() -> str:
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is not None:
        return _SYSTEM_PROMPT_CACHE
    from scripts.prompt_playground import SYSTEM_PROMPT
    _SYSTEM_PROMPT_CACHE = SYSTEM_PROMPT
    return _SYSTEM_PROMPT_CACHE


def _resolve_json_path(raw: str) -> Path:
    p = Path(raw).expanduser()
    if p.is_absolute():
        rp = p.resolve()
    else:
        rp = (_ROOT / p).resolve()
        try:
            rp.relative_to(_CODE_ROOT_RESOLVED)
        except ValueError:
            abort(400, description="json_path escapes the Code directory.")
    if not rp.exists():
        abort(404, description=f"json_path not found: {rp}")
    return rp


def _set_activity(session_id: str, phase: str, detail: str = ""):
    rec = _SESSION_ACTIVITY.get(session_id, {})
    old_phase = rec.get("phase")
    rec["session_id"] = session_id
    rec["phase"] = phase
    rec["detail"] = detail
    rec["updated_at"] = time.time()
    rec.setdefault("started_at", rec["updated_at"])
    _SESSION_ACTIVITY[session_id] = rec
    if old_phase != phase:
        elapsed = rec["updated_at"] - rec["started_at"]
        _LOG.info("[session %s] phase=%s elapsed=%.2fs detail=%s", session_id[:8], phase, elapsed, detail)


def _send_with_tools(chat: Any, message: str, max_rounds: int = 4) -> Any:
    response = chat.send_message(message)
    for _ in range(max_rounds):
        calls = list(getattr(response, "function_calls", None) or [])
        if not calls:
            return response
        followup_parts: list[Any] = []
        for call in calls:
            name = str(getattr(call, "name", "") or "")
            args = dict(getattr(call, "args", {}) or {})
            if name == "search_symbols":
                payload = _tool_search_symbols(
                    query=str(args.get("query", "") or ""),
                    limit=int(args.get("limit", 12) or 12),
                    lib=(str(args.get("lib")) if args.get("lib") is not None else None),
                )
            else:
                payload = {"error": f"Unknown function: {name}"}
            followup_parts.append(
                types.Part.from_function_response(name=name or "unknown_function", response=payload)
            )
        response = chat.send_message(followup_parts)
    return response


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def root_hint():
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>SchematIQ API</title></head>"
        "<body style='font-family:system-ui,sans-serif;max-width:42rem;margin:2rem;line-height:1.5'>"
        "<h1>SchematIQ API</h1>"
        "<p>This port serves <code>/api/*</code> only. Open the web UI at "
        "<a href='http://127.0.0.1:5173/'>http://127.0.0.1:5173/</a>.</p>"
        "<p>Health check: <a href='/api/health'>/api/health</a></p>"
        "</body></html>"
    )


@app.route("/api/health")
def health():
    if _GENAI_ERROR:
        gs = "error"
    elif _GENAI_READY.is_set():
        gs = "ready"
    else:
        gs = "loading"
    return jsonify({"ok": "true", "genai": gs})


@app.route("/api/projects")
def list_projects():
    data_dir = _ROOT / "data"
    paths = sorted(data_dir.glob("llm_output*.json"))
    return jsonify({"projects": [str(p) for p in paths]})


@app.route("/api/chat/activity", methods=["POST"])
def chat_activity():
    data = request.get_json(silent=True) or {}
    sid = data.get("session_id", "")
    rec = _SESSION_ACTIVITY.get(sid)
    if not rec:
        return jsonify({"session_id": sid, "phase": "idle", "detail": "", "elapsed_s": 0.0})
    out = dict(rec)
    started = float(out.get("started_at", out.get("updated_at", time.time())) or time.time())
    out["elapsed_s"] = max(0.0, time.time() - started)
    return jsonify(out)


@app.route("/api/symbols/search", methods=["POST"])
def search_symbols():
    data = request.get_json(silent=True) or {}
    return jsonify(_symbol_candidates_payload(
        query=data.get("query", ""),
        limit=data.get("limit", 12) or 12,
        lib=data.get("lib"),
    ))


@app.route("/api/symbols/batch_search", methods=["POST"])
def batch_search_symbols():
    data = request.get_json(silent=True) or {}
    return jsonify(_batch_symbol_candidates_payload(data.get("parts", []), top_k=data.get("top_k", 3) or 3))


@app.route("/api/chat/start", methods=["POST"])
def start_chat():
    _LOG.info("[chat/start] ── request received ──")
    # New chats without json_path only need a static welcome: skip _get_client() and chats.create here
    # so cold Render + slow google-genai import does not block the UI for minutes.
    data = request.get_json(silent=True) or {}
    json_path = data.get("json_path")

    state = _ProjectState()
    if json_path:
        p = _resolve_json_path(json_path)
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        state.project_name = d.get("project_name")
        state.description = d.get("description", "")
        state.sheets = list(d.get("sheets", []))
        state.components = list(d.get("components", []))
        state.passives = list(d.get("passives", []))
        state.nets = list(d.get("nets", []))
        state.output_json_path = p

    sid = str(uuid.uuid4())

    chat = None
    if json_path:
        t0 = time.perf_counter()
        client = _get_client()
        _LOG.info("[chat/start] client ready in %.2fs", time.perf_counter() - t0)
        try:
            chat = _create_gemini_chat(client)
        except Exception as e:
            _LOG.error("[chat/start] chats.create FAILED: %s", e)
            return _err(502, f"Gemini chat creation failed: {e}")

    _SESSIONS[sid] = {"sid": sid, "chat": chat, "state": state}
    _set_activity(sid, "starting_chat", "Initializing assistant")

    if json_path:
        seed_payload = json.dumps(state.to_dict(), indent=2)
        chat.send_message(
            "Continue editing this existing project JSON. Treat it as the current state.\n"
            "When proposing changes, output JSON blocks that can be merged into this state.\n\n"
            f"{seed_payload}"
        )
        opener = chat.send_message("I loaded an existing board. Ask me what should be changed next.")
    else:
        recent = _recent_project_jsons(limit=4)
        opener = None
        if recent:
            recent_list = "\n".join(f"- {p.name}" for p in recent)
            raw_text = (
                "Hello! Would you like to start a new project or continue from an existing one?\n\n"
                "If continuing, tell me the filename from this list:\n\n"
                f"{recent_list}"
            )
        else:
            raw_text = "Hello! Would you like to start a new project or continue from an existing one?"

    if opener is not None:
        _set_activity(sid, "waiting_for_model", "Generating first assistant message")
        raw_text = opener.text or ""

    _set_activity(sid, "processing_response", "Parsing assistant output")
    text = _strip_machine_blocks(raw_text)
    if not text:
        text = "Hello! Do you want to continue an existing project or start a new one?"

    captured: list[str] = []
    for b in _extract_json_blocks(raw_text):
        r = state.ingest(b)
        if r:
            captured.append(r)
    for b in _extract_new_component_blocks(raw_text):
        state.ingest_new_component(b)
        captured.append(f"new_component:{b.get('name', 'unknown')}")

    fix_notes: list[str] = []
    if _env_flag("SCHEMATIQ_CHAT_AUTOFIX", default=True):
        _set_activity(sid, "autofixing_symbols", "Resolving symbols from local cache")
        fix_notes = _autofix_unresolved_symbols(state)
    if fix_notes:
        note_lines = ["", "I auto-corrected symbol names to available KiCad library symbols:", *fix_notes[:8]]
        if len(fix_notes) > 8:
            note_lines.append(f"- ... and {len(fix_notes) - 8} more")
        text = (text + "\n" + "\n".join(note_lines)).strip()

    _set_activity(sid, "idle", "Ready")
    return jsonify({
        "session_id": sid,
        "assistant": text,
        "captured": captured,
        "state": state.to_dict(),
        "json_path": str(state.output_json_path) if state.output_json_path else None,
    })


@app.route("/api/chat/send", methods=["POST"])
def send_chat():
    data = request.get_json(silent=True) or {}
    sid = data.get("session_id", "")
    message = data.get("message", "")
    sess = _SESSIONS.get(sid)
    if not sess:
        return _err(404, "chat session not found")
    state: _ProjectState = sess["state"]

    loaded = _try_load_project_from_message(state, message)
    if loaded:
        _set_activity(sid, "loaded_project", f"Loaded {loaded.name}")
        _set_activity(sid, "preparing_gemini", "Preparing Gemini client…")
        summary = (
            f"Loaded `{loaded.name}`.\n"
            f"- Sheets: {len(state.sheets)}\n"
            f"- Components: {len(state.components)}\n"
            f"- Passives: {len(state.passives)}\n"
            f"- Nets: {len(state.nets)}\n"
            "Tell me exactly what to change, and I will keep it concise."
        )
        try:
            chat = _ensure_gemini_chat(sess)
        except Exception as e:
            _set_activity(sid, "error", str(e))
            return _err(502, f"Gemini chat creation failed: {e}")
        seed_payload = json.dumps(state.to_dict(), indent=2)
        chat.send_message(
            "This existing project JSON is now the authoritative working state. "
            "Use it exactly; do not assume missing sheets.\n\n"
            f"{seed_payload}"
        )
        _set_activity(sid, "idle", "Ready")
        return jsonify({"assistant": summary, "captured": ["loaded_project"], "state": state.to_dict()})

    goal_hint = _extract_goal_hint(message)
    if goal_hint:
        state.goal_summary = goal_hint

    _set_activity(
        sid,
        "preparing_gemini",
        "Preparing Gemini client (first message can take ~30–90s on a cold free host)…",
    )
    try:
        chat = _ensure_gemini_chat(sess)
    except Exception as e:
        _set_activity(sid, "error", str(e))
        return _err(502, f"Gemini chat creation failed: {e}")

    try:
        _set_activity(sid, "sending_to_model", "Submitting prompt to Gemini")
        planning_guard = (
            "If this request is complex (multi-sheet or full dev board), first propose a sheet-by-sheet plan "
            "and ask to proceed one sheet at a time. Do not jump to full design immediately."
        )
        goal_guard = f"Current fixed project objective: {state.goal_summary}" if state.goal_summary else ""
        user_msg = message + "\n\n" + planning_guard
        if goal_guard:
            user_msg += "\n" + goal_guard
        user_msg += "\n[Style rule: keep response short, max 5 bullets, no mention of JSON/code blocks.]"
        response = chat.send_message(user_msg)
        _set_activity(sid, "processing_response", "Parsing model response")
    except Exception as e:
        _set_activity(sid, "error", str(e))
        return _err(502, f"Gemini chat failed: {e}")

    raw_text = response.text or ""
    _set_activity(sid, "extracting_blocks", "Extracting JSON blocks")
    text = _concise_user_text(_strip_machine_blocks(raw_text))
    if not text:
        text = "I processed that. Tell me the next step you want, and I will continue."

    captured: list[str] = []
    json_blocks: list[dict[str, Any]] = []
    if not _env_flag("SCHEMATIQ_CHAT_SKIP_INGEST", default=False):
        _set_activity(sid, "ingesting_state", "Merging extracted blocks into project state")
        json_blocks = list(_extract_json_blocks(raw_text))
        for b in json_blocks:
            r = state.ingest(b)
            if r:
                captured.append(r)
        for b in _extract_new_component_blocks(raw_text):
            state.ingest_new_component(b)
            captured.append(f"new_component:{b.get('name', 'unknown')}")

    fix_notes: list[str] = []
    if _env_flag("SCHEMATIQ_CHAT_AUTOFIX", default=True):
        _set_activity(sid, "autofixing_symbols", "Resolving symbols from local cache")
        fix_notes = _autofix_unresolved_symbols(state)

    unresolved_lines: list[str] = []
    if _env_flag("SCHEMATIQ_CHAT_STRICT_UNRESOLVED", default=True):
        _set_activity(sid, "checking_unresolved_symbols", "Validating unresolved symbols")
        unresolved_lines = _unresolved_symbol_lines(state.to_dict())

    if fix_notes:
        lines = ["", "I auto-corrected symbol names to available KiCad library symbols:", *fix_notes[:8]]
        if len(fix_notes) > 8:
            lines.append(f"- ... and {len(fix_notes) - 8} more")
        text = _concise_user_text((text + "\n" + "\n".join(lines)).strip())

    if unresolved_lines:
        lines = [
            "",
            "I still need exact KiCad symbols for some parts before generation.",
            "I can continue once you confirm exact part names (or tell me to pick from closest official symbols).",
        ]
        text = text + "\n" + "\n".join(lines)

    _set_activity(sid, "idle", "Ready")
    return jsonify({"assistant": text, "captured": captured, "state": state.to_dict()})


@app.route("/api/chat/save", methods=["POST"])
def save_chat():
    data = request.get_json(silent=True) or {}
    sid = data.get("session_id", "")
    sess = _SESSIONS.get(sid)
    if not sess:
        return _err(404, "chat session not found")
    state: _ProjectState = sess["state"]
    path = _save_state(state)
    return jsonify({"json_path": str(path), "state": state.to_dict()})


@app.route("/api/run", methods=["POST"])
def run_action():
    data = request.get_json(silent=True) or {}
    action = (data.get("action", "")).strip().lower()
    raw_path = data.get("json_path", "")
    target = (data.get("target") or "both").strip().lower()
    placement = (data.get("placement") or "").strip().lower()

    t0 = time.time()
    json_path = _resolve_json_path(raw_path)

    try:
        with open(json_path, encoding="utf-8") as f:
            design = json.load(f)
    except Exception as e:
        return _err(400, f"Failed reading JSON: {e}")

    fix_notes = _autofix_unresolved_symbols_in_design(design)
    if fix_notes:
        with open(json_path, "w", encoding="utf-8") as wf:
            json.dump(design, wf, indent=2)
            wf.write("\n")

    if action not in ("generate", "check", "review", "repair", "validate"):
        return _err(400, "invalid action")

    if action in ("generate", "check", "review", "validate"):
        lines = _unresolved_symbol_lines(design)
        if lines:
            return jsonify({
                "command": [], "cwd": str(_ROOT), "exit_code": 2,
                "stdout": "", "stderr": "Symbol resolution failed.\n" + "\n".join(lines),
                "kicad_pro_path": None,
            })

    if action == "generate":
        cmd = [sys.executable, "scripts/generate_from_llm.py"]
        if placement in ("llm", "llm_place", "llm-place"):
            cmd.append("--llm-place")
        slow = os.getenv("SCHEMATIQ_SLOW_GEN", "").strip().lower() in ("1", "true", "yes")
        cmd.append("--validate" if slow else "--quick")
        cmd.extend(["--target", target, str(json_path)])
    elif action == "check":
        cmd = [sys.executable, "scripts/generate_from_llm.py", "--repair", "--review", "--validate", "--target", "kicad", str(json_path)]
    elif action == "review":
        cmd = [sys.executable, "scripts/review_llm_json.py", str(json_path), "--fail-on", "none"]
    elif action == "repair":
        cmd = [sys.executable, "scripts/generate_from_llm.py", "--repair", "--target", "kicad", str(json_path)]
    else:
        cmd = [sys.executable, "scripts/generate_from_llm.py", "--validate", "--target", "kicad", str(json_path)]

    proc = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True)
    kicad_pro_path = None
    if action == "generate":
        m = re.search(r'(/[^\s\'"]+\.kicad_pro)\b', f"{proc.stdout}\n{proc.stderr}")
        if m:
            kicad_pro_path = m.group(1)

    return jsonify({
        "command": cmd, "cwd": str(_ROOT), "exit_code": proc.returncode,
        "stdout": proc.stdout, "stderr": proc.stderr,
        "kicad_pro_path": kicad_pro_path, "elapsed_s": time.time() - t0,
    })


# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Local dev: 127.0.0.1 + SCHEMATIQ_WEBUI_PORT (default 5179).
    # On Render, use gunicorn (see render.yaml); this branch is for local `python scripts/...` only.
    on_render = bool(os.getenv("RENDER"))
    if on_render:
        port = int(os.getenv("PORT", "10000"))
        host = os.getenv("SCHEMATIQ_HOST", "0.0.0.0")
    else:
        port = int(os.getenv("SCHEMATIQ_WEBUI_PORT", os.getenv("PORT", "5179")))
        host = os.getenv("SCHEMATIQ_HOST", "127.0.0.1")
    print(f"SchematIQ Flask API on http://{host}:{port}  (health: /api/health)", flush=True)
    app.run(host=host, port=port, debug=False, threaded=True)
