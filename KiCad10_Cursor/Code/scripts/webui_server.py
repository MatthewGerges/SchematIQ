#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# google-genai is imported lazily on first use via _ensure_genai().
# Do NOT import at module level or in startup events — it hangs in both
# uvicorn --reload subprocesses AND startup event handlers.
genai = None  # type: ignore[assignment]
types = None  # type: ignore[assignment]
GoogleSearch = None  # type: ignore[assignment]
Tool = None  # type: ignore[assignment]


def _ensure_genai():
    """Import google-genai on first use. Safe without --reload."""
    global genai, types, GoogleSearch, Tool
    if genai is not None:
        return
    try:
        from google import genai as _genai
        from google.genai import types as _types
        from google.genai.types import GoogleSearch as _GS, Tool as _Tool
        genai = _genai
        types = _types
        GoogleSearch = _GS
        Tool = _Tool
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                f"google-genai failed to import: {e}. "
                "From the Code/ directory: source .venv/bin/activate && "
                "pip install --upgrade --force-reinstall google-genai && pip install -r requirements.txt"
            ),
        ) from e

_ROOT = Path(__file__).resolve().parent.parent
_CODE_ROOT_RESOLVED = _ROOT.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))



load_dotenv(_ROOT / ".env")


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
_SESSION_ACTIVITY: dict[str, dict[str, Any]] = {}
_LOG = logging.getLogger("schematiq.webui")

# Singleton Gemini client — creating a new genai.Client() on every request
# is expensive (HTTP/gRPC transport setup). Reuse one for the server lifetime.
_GENAI_CLIENT: Any = None


def _get_genai_client() -> Any:
    """Return a cached genai.Client, creating one on first call."""
    global _GENAI_CLIENT
    if _GENAI_CLIENT is not None:
        return _GENAI_CLIENT
    _ensure_genai()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise Exception("GEMINI_API_KEY not set in Code/.env")
    _GENAI_CLIENT = genai.Client(api_key=api_key)
    return _GENAI_CLIENT


def _configure_schematiq_logging() -> None:
    """Ensure ``schematiq.webui`` INFO lines appear (uvicorn access log is separate)."""
    lvl_name = os.getenv("SCHEMATIQ_LOG_LEVEL", "INFO").upper()
    lvl = getattr(logging, lvl_name, logging.INFO)
    lg = logging.getLogger("schematiq.webui")
    if not lg.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(levelname)s [schematiq] %(message)s"))
        lg.addHandler(h)
    lg.setLevel(lvl)
    lg.propagate = False


_configure_schematiq_logging()

# NOTE: Do NOT add @app.on_event("startup") handlers that import google-genai
# or create genai.Client — they hang. All heavy resources are loaded lazily
# on first request instead.


def _extract_json_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if not text or "```json" not in text:
        return blocks
    i = 0
    while True:
        start = text.find("```json", i)
        if start < 0:
            break
        nl = text.find("\n", start)
        if nl < 0:
            break
        end = text.find("```", nl + 1)
        if end < 0:
            break
        payload = text[nl + 1 : end].strip()
        if payload:
            try:
                blocks.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
        i = end + 3
    return blocks


def _extract_new_component_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if not text or "```new_component" not in text:
        return blocks
    i = 0
    needle = "```new_component"
    while True:
        start = text.find(needle, i)
        if start < 0:
            break
        nl = text.find("\n", start)
        if nl < 0:
            break
        end = text.find("```", nl + 1)
        if end < 0:
            break
        payload = text[nl + 1 : end].strip()
        if payload:
            try:
                blocks.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
        i = end + 3
    return blocks


def _strip_machine_blocks(text: str) -> str:
    """Hide machine-oriented fenced payloads from end-user chat rendering."""
    if not text:
        return ""
    out = re.sub(r"```json\s*\n.*?```", "", text, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"```new_component\s*\n.*?```", "", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"(?im)^.*\bhere(?:'s| is)\b.*\bjson\b.*$", "", out)
    out = re.sub(r"(?im)^.*\bjson\b.*code block.*$", "", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def _concise_user_text(text: str, max_lines: int = 8) -> str:
    """Keep assistant replies compact for chat UI readability."""
    if not text:
        return text
    lines = [ln.rstrip() for ln in text.splitlines()]
    # Drop empty tail noise, keep compact body.
    while lines and not lines[-1].strip():
        lines.pop()
    # Do not hard-truncate content; prompt style rules already keep responses concise.
    return "\n".join(lines).strip()


def _env_flag(name: str, default: bool = True) -> bool:
    v = str(os.getenv(name, "")).strip().lower()
    if not v:
        return default
    return v not in ("0", "false", "no", "off")


def _min_pin_count_from_connections(comp: dict[str, Any]) -> int:
    conns = comp.get("connections") or []
    max_n = 0
    for c in conns:
        p = str(c.get("pin", "")).strip()
        if p.isdigit():
            max_n = max(max_n, int(p))
    return max(max_n, len(conns))


def _canonical_lookup_from_resolved(sym_name: str, kind: str, path: str) -> str:
    if kind == "packed":
        return f"{Path(path).stem}:{sym_name}"
    if kind == "unpacked_single":
        from src.lib.kicad_library_paths import lib_prefix_from_unpacked_symbol_file

        return f"{lib_prefix_from_unpacked_symbol_file(path)}:{sym_name}"
    return sym_name


def _autofix_unresolved_symbols(state: "_ProjectState") -> list[str]:
    """
    Auto-correct unresolved component symbols using local KiCad symbol indexes.

    Uses the pre-built JSON cache (``by_lookup`` dict) for O(1) validation
    instead of the slow filesystem-based ``preview_resolve()``.

    Returns user-facing notes for applied fixes.
    """
    from src.lib.symbol_aliases import apply_symbol_alias, normalize_symbol_lookup
    from src.lib.kicad_symbol_cache import ensure_symbol_cache, suggest_symbol_from_cache, search_symbol_candidates

    t0 = time.perf_counter()
    cache = ensure_symbol_cache()
    dt_load = time.perf_counter() - t0
    by_lookup = cache.get("by_lookup") or {} if cache else {}
    n_rec = len(by_lookup)
    _LOG.info(
        "[autofix] cache loaded %.2fs (%s lookups); %s components",
        dt_load,
        n_rec,
        len(state.components),
    )

    notes: list[str] = []
    loop0 = time.perf_counter()
    for i, comp in enumerate(state.components):
        raw_part = str(comp.get("part", "")).strip()
        if not raw_part:
            continue
        lookup = normalize_symbol_lookup(apply_symbol_alias(raw_part))

        # Fast O(1) cache check — if the lookup is in the cache it's a valid symbol.
        if lookup in by_lookup:
            continue

        # Try to find a fix using the cache (fuzzy matching, prefix, etc.)
        fixed_lookup: str | None = suggest_symbol_from_cache(lookup, cache)

        # Fallback: broader fuzzy search if suggest didn't find anything
        if not fixed_lookup or fixed_lookup not in by_lookup:
            candidates = search_symbol_candidates(lookup, cache, limit=1)
            if candidates:
                fixed_lookup = str(candidates[0].get("lookup", ""))

        if not fixed_lookup or fixed_lookup not in by_lookup:
            continue
        if fixed_lookup != raw_part:
            comp["part"] = fixed_lookup
            notes.append(f"- {comp.get('ref', '?')}: `{raw_part}` → `{fixed_lookup}`")
    _LOG.info("[autofix] done in %.2fs (%s rewrites)", time.perf_counter() - loop0, len(notes))
    return notes


def _autofix_unresolved_symbols_in_design(design: dict[str, Any]) -> list[str]:
    """
    Auto-fix unresolved symbols directly in a persisted design dict.
    Uses cache-based O(1) lookups instead of slow filesystem scanning.
    Returns change notes.
    """
    from src.lib.kicad_symbol_cache import ensure_symbol_cache, suggest_symbol_from_cache, search_symbol_candidates
    from src.lib.symbol_aliases import apply_symbol_alias, normalize_symbol_lookup

    cache = ensure_symbol_cache()
    by_lookup = cache.get("by_lookup") or {} if cache else {}
    notes: list[str] = []
    for comp in design.get("components", []):
        raw_part = str(comp.get("part", "")).strip()
        if not raw_part:
            continue
        lookup = normalize_symbol_lookup(apply_symbol_alias(raw_part))
        if lookup in by_lookup:
            continue
        fixed_lookup = suggest_symbol_from_cache(lookup, cache)
        # Fallback: broader fuzzy search if suggest didn't find anything
        if not fixed_lookup or fixed_lookup not in by_lookup:
            candidates = search_symbol_candidates(lookup, cache, limit=1)
            if candidates:
                fixed_lookup = str(candidates[0].get("lookup", ""))
        if not fixed_lookup or fixed_lookup not in by_lookup:
            continue
        if fixed_lookup != raw_part:
            comp["part"] = fixed_lookup
            notes.append(f"- {comp.get('ref', '?')}: `{raw_part}` → `{fixed_lookup}`")
    return notes


def _symbol_candidates_payload(query: str, limit: int = 12, lib: str | None = None) -> dict[str, Any]:
    from src.lib.kicad_symbol_cache import ensure_symbol_cache, search_symbol_candidates

    q = (query or "").strip()
    if not q:
        return {"query": q, "lib": lib, "candidates": []}
    cache = ensure_symbol_cache()
    candidates = search_symbol_candidates(q, cache, limit=limit, lib=lib)
    return {"query": q, "lib": lib, "candidates": candidates}


def _batch_symbol_candidates_payload(parts: list[str], top_k: int = 3) -> dict[str, Any]:
    from src.lib.kicad_symbol_cache import ensure_symbol_cache, search_symbol_candidates
    from src.lib.symbol_aliases import apply_symbol_alias, normalize_symbol_lookup

    cache = ensure_symbol_cache()
    k = max(1, min(int(top_k or 3), 10))
    out: dict[str, list[dict[str, str]]] = {}
    seen: set[str] = set()
    for raw in parts:
        part = str(raw or "").strip()
        if not part:
            continue
        if part in seen:
            continue
        seen.add(part)
        lookup = normalize_symbol_lookup(apply_symbol_alias(part))
        candidates = search_symbol_candidates(lookup, cache, limit=k)
        out[part] = [
            {"lookup": str(c.get("lookup", "")), "lib": str(c.get("lib", "")), "symbol": str(c.get("symbol", ""))}
            for c in candidates
        ]
    return {"top_k": k, "results": out}


def _tool_search_symbols(query: str, limit: int = 12, lib: str | None = None) -> dict[str, Any]:
    """
    Search local KiCad symbol cache and return valid lookup candidates.

    Args:
      query: Free-text symbol query such as "TPS63900" or "Conn_01x04".
      limit: Max candidates to return (default 12, max 50).
      lib: Optional KiCad library name to restrict search (e.g. "Device").
    """
    safe_limit = max(1, min(int(limit or 12), 50))
    return _symbol_candidates_payload(query=query, limit=safe_limit, lib=lib)


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
        self.goal_summary: str = ""

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


def _load_project_into_state(state: "_ProjectState", path: Path) -> None:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    state.project_name = data.get("project_name")
    state.description = data.get("description", "")
    state.sheets = list(data.get("sheets", []))
    state.components = list(data.get("components", []))
    state.passives = list(data.get("passives", []))
    state.nets = list(data.get("nets", []))
    state.output_json_path = path


def _try_load_project_from_message(state: "_ProjectState", message: str) -> Path | None:
    """
    If user message mentions an existing llm_output*.json filename, load it.
    """
    m = re.search(r"\b(llm_output[^\s`\"']*?\.json)\b", message, flags=re.IGNORECASE)
    if not m:
        return None
    fname = m.group(1)
    for p in _recent_project_jsons(limit=200):
        if p.name.lower() == fname.lower():
            _load_project_into_state(state, p)
            return p
    return None


def _extract_goal_hint(message: str) -> str:
    txt = (message or "").strip()
    if not txt:
        return ""
    low = txt.lower()
    # Keep this tiny and deterministic for now.
    if "nrf5340" in low:
        return "Design target is an nRF5340-based board."
    if "stm32" in low:
        return "Design target is an STM32-based board."
    return ""


def _underconnected_net_lines(design: dict[str, Any]) -> list[str]:
    """
    Return nets with fewer than two endpoints in the assembled design.
    """
    net_counts: dict[str, int] = {}
    for comp in design.get("components", []):
        for c in comp.get("connections", []) or []:
            n = str(c.get("net", "")).strip()
            if n:
                net_counts[n] = net_counts.get(n, 0) + 1
    for p in design.get("passives", []):
        for c in p.get("connections", []) or []:
            n = str(c.get("net", "")).strip()
            if n:
                net_counts[n] = net_counts.get(n, 0) + 1
    bad = sorted([n for n, k in net_counts.items() if k < 2 and n.upper() not in ("NC", "N/C")])
    if not bad:
        return []
    lines = [f"Connectivity guard: {len(bad)} underconnected net(s) found (<2 endpoints)."]
    for n in bad[:16]:
        lines.append(f"- {n}")
    if len(bad) > 16:
        lines.append(f"- ... and {len(bad) - 16} more")
    return lines


def _unresolved_symbol_lines(design: dict[str, Any]) -> list[str]:
    """Return human-readable unresolved symbol lines using the O(1) symbol cache.

    Replaces the old ``symbol_preflight.find_unresolved_components`` which
    called ``preview_resolve()`` per-component (filesystem scan, ~3 min).
    """
    from src.lib.kicad_symbol_cache import ensure_symbol_cache
    from src.lib.symbol_aliases import apply_symbol_alias, normalize_symbol_lookup

    cache = ensure_symbol_cache()
    by_lookup = cache.get("by_lookup") or {} if cache else {}
    if not by_lookup:
        return []  # No cache → can't validate, skip

    unresolved: list[dict[str, str]] = []
    sheets = {s["name"] for s in design.get("sheets", [])}
    for comp in design.get("components", []):
        sheet = comp.get("sheet", "")
        if sheets and sheet and sheet not in sheets:
            continue
        raw = str(comp.get("part", "")).strip()
        if not raw:
            continue
        lookup = normalize_symbol_lookup(apply_symbol_alias(raw))
        if lookup not in by_lookup:
            unresolved.append({
                "ref": comp.get("ref", "?"),
                "part": raw,
                "lookup": lookup,
            })

    if not unresolved:
        return []
    lines = [f"Strict symbol mode: {len(unresolved)} unresolved symbol(s)."]
    for u in unresolved[:12]:
        lines.append(f"- {u['ref']}: {u['part']} (lookup: {u['lookup']})")
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


def _send_with_tools(chat: Any, message: str, max_rounds: int = 4) -> Any:
    """
    Send message to Gemini and explicitly service function calls.

    We disable SDK automatic function calling and perform deterministic dispatch
    so backend-owned tools (local cache search) run under our control.
    """
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
                types.Part.from_function_response(
                    name=name or "unknown_function",
                    response=payload,
                )
            )
        response = chat.send_message(followup_parts)
    return response


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
        raise Exception(f"json_path not found: {rp}")
    return rp


def _set_activity(session_id: str, phase: str, detail: str = "") -> None:
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


def list_projects() -> dict[str, Any]:
    data_dir = _ROOT / "data"
    paths = sorted(data_dir.glob("llm_output*.json"))
    return {"projects": [str(p) for p in paths]}


def health() -> dict[str, str]:
    return {"ok": "true"}


def chat_activity(req: ChatActivityRequest) -> dict[str, Any]:
    rec = _SESSION_ACTIVITY.get(req.session_id)
    if not rec:
        return {"session_id": req.session_id, "phase": "idle", "detail": "", "elapsed_s": 0.0}
    out = dict(rec)
    started = float(out.get("started_at", out.get("updated_at", time.time())) or time.time())
    out["elapsed_s"] = max(0.0, time.time() - started)
    return out


def search_symbols(req: SymbolSearchRequest) -> dict[str, Any]:
    return _symbol_candidates_payload(
        query=req.query,
        limit=req.limit or 12,
        lib=req.lib,
    )


def batch_search_symbols(req: SymbolBatchSearchRequest) -> dict[str, Any]:
    return _batch_symbol_candidates_payload(req.parts, top_k=req.top_k or 3)


def start_chat(req: ChatStartRequest) -> dict[str, Any]:
    _LOG.info("[chat/start] ── request received ──")
    t_total = time.perf_counter()

    t0 = time.perf_counter()
    client = _get_genai_client()
    _LOG.info("[chat/start] client ready in %.2fs", time.perf_counter() - t0)

    t0 = time.perf_counter()
    try:
        chat = client.chats.create(
            model=MODEL,
            config=types.GenerateContentConfig(
                system_instruction=_system_prompt(),
            ),
        )
    except Exception as e:
        _LOG.error("[chat/start] chats.create FAILED after %.2fs: %s", time.perf_counter() - t0, e)
        raise HTTPException(status_code=502, detail=f"Gemini chat creation failed: {e}") from e
    _LOG.info("[chat/start] chat created in %.2fs", time.perf_counter() - t0)
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
    _set_activity(sid, "starting_chat", "Initializing assistant")
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
        opener = chat.send_message("I loaded an existing board. Ask me what should be changed next.")
    else:
        recent = _recent_project_jsons(limit=4)
        if recent:
            recent_list = "\n".join(f"- {p.name}" for p in recent)
            # Keep first assistant message deterministic for UI consistency.
            opener = None
            raw_text = (
                "Hello! Would you like to start a new project or continue from an existing one?\n\n"
                "If continuing, tell me the filename from this list:\n\n"
                f"{recent_list}"
            )
        else:
            opener = None
            raw_text = "Hello! Would you like to start a new project or continue from an existing one?"
    if opener is not None:
        _set_activity(sid, "waiting_for_model", "Generating first assistant message")
        raw_text = opener.text or ""
    _set_activity(sid, "processing_response", "Parsing assistant output")
    text = _strip_machine_blocks(raw_text)
    if not text:
        text = (
            "Hello! Do you want to continue an existing project or start a new one? "
            "I can suggest only valid KiCad symbols from the local cache."
        )
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
        note_lines = [
            "",
            "I auto-corrected symbol names to available KiCad library symbols:",
            *fix_notes[:8],
        ]
        if len(fix_notes) > 8:
            note_lines.append(f"- ... and {len(fix_notes) - 8} more")
        text = (text + "\n" + "\n".join(note_lines)).strip()
    _set_activity(sid, "idle", "Ready")
    return {
        "session_id": sid,
        "assistant": text,
        "captured": captured,
        "state": state.to_dict(),
        "json_path": str(state.output_json_path) if state.output_json_path else None,
    }


def send_chat(req: ChatSendRequest) -> dict[str, Any]:
    sess = _SESSIONS.get(req.session_id)
    if not sess:
        raise Exception("chat session not found")
    chat = sess["chat"]
    state: _ProjectState = sess["state"]
    loaded = _try_load_project_from_message(state, req.message)
    if loaded:
        _set_activity(req.session_id, "loaded_project", f"Loaded {loaded.name}")
        summary = (
            f"Loaded `{loaded.name}`.\n"
            f"- Sheets: {len(state.sheets)}\n"
            f"- Components: {len(state.components)}\n"
            f"- Passives: {len(state.passives)}\n"
            f"- Nets: {len(state.nets)}\n"
            "Tell me exactly what to change, and I will keep it concise."
        )
        seed_payload = json.dumps(state.to_dict(), indent=2)
        seed_prompt = (
            "This existing project JSON is now the authoritative working state. "
            "Use it exactly; do not assume missing sheets.\n\n"
            f"{seed_payload}"
        )
        chat.send_message(seed_prompt)
        _set_activity(req.session_id, "idle", "Ready")
        return {"assistant": summary, "captured": ["loaded_project"], "state": state.to_dict()}

    goal_hint = _extract_goal_hint(req.message)
    if goal_hint:
        state.goal_summary = goal_hint

    try:
        _set_activity(req.session_id, "sending_to_model", "Submitting prompt to Gemini")
        planning_guard = (
            "If this request is complex (multi-sheet or full dev board), first propose a sheet-by-sheet plan "
            "and ask to proceed one sheet at a time. Do not jump to full design immediately."
        )
        goal_guard = f"Current fixed project objective: {state.goal_summary}" if state.goal_summary else ""
        user_msg = req.message + "\n\n" + planning_guard
        if goal_guard:
            user_msg += "\n" + goal_guard
        user_msg += "\n[Style rule: keep response short, max 5 bullets, no mention of JSON/code blocks.]"
        response = chat.send_message(user_msg)
        _set_activity(req.session_id, "processing_response", "Parsing model response")
    except Exception as e:  # noqa: BLE001
        _set_activity(req.session_id, "error", str(e))
        raise HTTPException(status_code=502, detail=f"Gemini chat failed: {e}") from e
    raw_text = response.text or ""
    _set_activity(req.session_id, "extracting_blocks", "Extracting JSON blocks")
    text = _concise_user_text(_strip_machine_blocks(raw_text))
    if not text:
        text = "I processed that. Tell me the next step you want, and I will continue."
    captured: list[str] = []
    json_blocks: list[dict[str, Any]] = []
    dt_ingest = 0.0
    if _env_flag("SCHEMATIQ_CHAT_SKIP_INGEST", default=False):
        _set_activity(req.session_id, "ingesting_state", "Diagnostic mode: skipping JSON ingest")
    else:
        _set_activity(req.session_id, "ingesting_state", "Merging extracted blocks into project state")
        json_blocks = list(_extract_json_blocks(raw_text))
        t_ingest0 = time.perf_counter()
        for b in json_blocks:
            r = state.ingest(b)
            if r:
                captured.append(r)
        for b in _extract_new_component_blocks(raw_text):
            state.ingest_new_component(b)
            captured.append(f"new_component:{b.get('name', 'unknown')}")
        dt_ingest = time.perf_counter() - t_ingest0

    fix_notes: list[str] = []
    dt_fix = 0.0
    if _env_flag("SCHEMATIQ_CHAT_AUTOFIX", default=True):
        _set_activity(req.session_id, "autofixing_symbols", "Resolving symbols from local cache")
        t_fix0 = time.perf_counter()
        fix_notes = _autofix_unresolved_symbols(state)
        dt_fix = time.perf_counter() - t_fix0

    dt_unresolved = 0.0
    unresolved_lines: list[str] = []
    if _env_flag("SCHEMATIQ_CHAT_STRICT_UNRESOLVED", default=True):
        _set_activity(req.session_id, "checking_unresolved_symbols", "Validating unresolved symbols")
        t_unres0 = time.perf_counter()
        unresolved_lines = _unresolved_symbol_lines(state.to_dict())
        dt_unresolved = time.perf_counter() - t_unres0

    if dt_ingest > 0.5 or dt_fix > 0.5 or dt_unresolved > 0.5:
        _LOG.info(
            "[session %s] post-model local work: ingest=%.2fs (blocks=%d, components=%d) autofix=%.2fs unresolved=%.2fs",
            req.session_id[:8],
            dt_ingest,
            len(json_blocks),
            len(state.components),
            dt_fix,
            dt_unresolved,
        )
    if fix_notes:
        lines = [
            "",
            "I auto-corrected symbol names to available KiCad library symbols:",
            *fix_notes[:8],
        ]
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
    _set_activity(req.session_id, "idle", "Ready")

    return {"assistant": text, "captured": captured, "state": state.to_dict()}


def save_chat(req: ChatSessionRequest) -> dict[str, Any]:
    sess = _SESSIONS.get(req.session_id)
    if not sess:
        raise Exception("chat session not found")
    state: _ProjectState = sess["state"]
    t0 = time.time()
    path = _save_state(state)
    _LOG.info("[session %s] save_chat path=%s dt=%.2fs", req.session_id[:8], path, time.time() - t0)
    return {"json_path": str(path), "state": state.to_dict()}


def _api_slow_full_kicad_gen() -> bool:
    """``SCHEMATIQ_SLOW_GEN=1`` restores full subprocess symbol validation plus post-verify (slower)."""
    return os.getenv("SCHEMATIQ_SLOW_GEN", "").strip().lower() in ("1", "true", "yes")


def run_action(req: RunRequest) -> dict[str, Any]:
    t0 = time.time()
    _LOG.info("[run] start action=%s json_path=%s target=%s placement=%s", req.action, req.json_path, req.target, req.placement)
    t_pre0 = time.time()
    json_path = _resolve_json_path(req.json_path)
    # Hard gate: no generation/review/check with unresolved symbol names.
    try:
        with open(json_path, encoding="utf-8") as f:
            design = json.load(f)
    except Exception as e:
        raise Exception(f"Failed reading JSON: {e}") from e

    # Pre-resolution: repair from local cache before strict gate.
    fix_notes = _autofix_unresolved_symbols_in_design(design)
    if fix_notes:
        try:
            with open(json_path, "w", encoding="utf-8") as wf:
                json.dump(design, wf, indent=2)
                wf.write("\n")
        except Exception as e:
            raise Exception(f"Failed writing symbol-fixed JSON: {e}") from e

    action = req.action.strip().lower()
    if action not in ("generate", "check", "review", "repair", "validate"):
        raise Exception("invalid action")

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
        # Connectivity underconnected-net guard intentionally disabled per user request.

    if action == "generate":
        target = (req.target or "both").strip().lower()
        if target not in ("kicad", "tscircuit", "both"):
            raise Exception("invalid target")
        cmd = [
            sys.executable,
            "scripts/generate_from_llm.py",
            *(
                ["--llm-place"]
                if (req.placement or "").strip().lower() in ("llm", "llm_place", "llm-place")
                else []
            ),
        ]
        if _api_slow_full_kicad_gen():
            cmd.append("--validate")
        else:
            cmd.append("--quick")
        cmd.extend(["--target", target, str(json_path)])
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
    preprocess_s = time.time() - t_pre0
    t_sub0 = time.time()
    proc = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True)
    subprocess_s = time.time() - t_sub0
    total_s = time.time() - t0
    kicad_pro_path = None
    if action == "generate":
        m = re.search(r'(/[^\s\'"]+\.kicad_pro)\b', f"{proc.stdout}\n{proc.stderr}")
        if m:
            kicad_pro_path = m.group(1)
    result = {
        "command": cmd,
        "cwd": str(_ROOT),
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "kicad_pro_path": kicad_pro_path,
        "preprocess_s": preprocess_s,
        "subprocess_s": subprocess_s,
        "elapsed_s": total_s,
    }
    _LOG.info(
        "[run] done action=%s exit=%s total=%.2fs preprocess=%.2fs subprocess=%.2fs",
        action,
        proc.returncode,
        total_s,
        preprocess_s,
        subprocess_s,
    )
    return result


def main() -> int:
    # Lazy import so requirements are only needed when running the server
    import uvicorn

    port = int(os.getenv("SCHEMATIQ_WEBUI_PORT") or os.getenv("CHIPCHAT_WEBUI_PORT", "5179"))
    print(f"SchematIQ API listening on http://127.0.0.1:{port}  (health: /api/health)", flush=True)
    uvicorn.run("scripts.webui_server:app", host="127.0.0.1", port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

