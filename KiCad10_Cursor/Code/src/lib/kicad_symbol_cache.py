from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from src.lib.kicad_library_paths import official_kicad_symbols_root


_CODE_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CACHE_PATH = _CODE_ROOT / "data" / "kicad_symbol_cache.json"
_REPO_ROOT = _CODE_ROOT.parent

# Avoid re-reading/parsing megabyte-scale JSON every symbol search batch.
_MEMORY_LOADS: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


def default_cache_path() -> Path:
    return _DEFAULT_CACHE_PATH


def build_symbol_cache(path: Path | None = None) -> dict[str, Any]:
    """
    Build and persist a cache of resolvable KiCad symbols.

    Cache shape intentionally stays simple for stable, fast lookups.
    """
    out_path = path or _DEFAULT_CACHE_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, str]] = []
    by_lookup: dict[str, dict[str, str]] = {}
    by_lib: dict[str, list[dict[str, str]]] = {}

    def _push(lookup: str, lib: str, sym: str) -> None:
        rec = {"lookup": lookup, "lib": lib, "symbol": sym}
        records.append(rec)
        by_lookup[lookup] = rec
        if lib:
            by_lib.setdefault(lib, []).append(rec)

    # 1) Custom symbols as bare lookup names.
    custom_dir = _REPO_ROOT / "KICAD_Library" / "Symbols"
    if custom_dir.is_dir():
        for fn in sorted(os.listdir(custom_dir)):
            if not fn.endswith(".kicad_sym"):
                continue
            sym = fn[: -len(".kicad_sym")]
            _push(sym, "", sym)

    # 2) Official unpacked and packed symbols
    off_root = official_kicad_symbols_root()
    if off_root and os.path.isdir(off_root):
        from src.lib.symbol_resolver import list_top_level_symbols_in_packed
        for top in sorted(os.listdir(off_root)):
            if top.endswith(".kicad_symdir"):
                lib = top[: -len(".kicad_symdir")]
                lib_dir = os.path.join(off_root, top)
                if not os.path.isdir(lib_dir):
                    continue
                try:
                    names = sorted(os.listdir(lib_dir))
                except OSError:
                    continue
                for fn in names:
                    if not fn.endswith(".kicad_sym"):
                        continue
                    sym = fn[: -len(".kicad_sym")]
                    _push(f"{lib}:{sym}", lib, sym)
            elif top.endswith(".kicad_sym"):
                lib = top[: -len(".kicad_sym")]
                lib_path = os.path.join(off_root, top)
                if not os.path.isfile(lib_path):
                    continue
                for sym in list_top_level_symbols_in_packed(lib_path):
                    _push(f"{lib}:{sym}", lib, sym)

    payload: dict[str, Any] = {
        "version": 1,
        "generated_at_unix": int(time.time()),
        "count": len(records),
        "records": records,
        "by_lookup": by_lookup,
        "by_lib": by_lib,
    }
    # Compact JSON: faster load/parse than pretty-printed multi-hundred-KB caches.
    out_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    invalidate_symbol_memory_cache(out_path)
    return payload


def load_symbol_cache(path: Path | None = None) -> dict[str, Any] | None:
    p = path or _DEFAULT_CACHE_PATH
    rp = os.path.abspath(str(p))
    if not os.path.isfile(rp):
        return None
    try:
        st = os.stat(rp)
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    memo = _MEMORY_LOADS.get(rp)
    if memo and memo[0] == sig:
        return memo[1]

    try:
        payload = json.loads(Path(rp).read_text(encoding="utf-8"))
    except Exception:
        return None

    _MEMORY_LOADS[rp] = (sig, payload)
    return payload


def invalidate_symbol_memory_cache(path: Path | None = None) -> None:
    """Drop in-memory cached JSON after rebuilding kicad_symbol_cache.json."""
    rp = os.path.abspath(str(path or _DEFAULT_CACHE_PATH))
    _MEMORY_LOADS.pop(rp, None)


def ensure_symbol_cache(path: Path | None = None) -> dict[str, Any]:
    cache = load_symbol_cache(path)
    if cache is not None:
        return cache
    return build_symbol_cache(path)


def _ensure_derived_indexes(cache: dict[str, Any]) -> None:
    """
    In-memory only: bucket records by first 4 uppercase symbol chars so bare
    lookups do not scan hundreds of thousands of records.
    """
    if cache.get("__derived_v1"):
        return
    buckets: dict[str, list[dict[str, str]]] = {}
    for r in cache.get("records") or []:
        sym = str(r.get("symbol", ""))
        if not sym:
            continue
        su = sym.upper()
        key = su[:4] if len(su) >= 4 else su
        buckets.setdefault(key, []).append(r)
    cache["__bare_sym_buckets"] = buckets
    cache["__derived_v1"] = True


def suggest_symbol_from_cache(lookup: str, cache: dict[str, Any] | None) -> str | None:
    """
    Return the best cache-backed symbol lookup for a requested lookup.
    """
    if not lookup or not cache:
        return None

    by_lookup = cache.get("by_lookup") or {}
    exact = by_lookup.get(lookup)
    if isinstance(exact, dict):
        return str(exact.get("lookup") or "")

    if ":" in lookup:
        lib, sym = lookup.split(":", 1)
        lib = lib.strip()
        sym = sym.strip()
        by_lib_raw = cache.get("by_lib") or {}
        candidates = by_lib_raw.get(lib)
        if not candidates:
            lib_u = lib.upper()
            for k_bl, recs in by_lib_raw.items():
                if isinstance(k_bl, str) and k_bl.upper() == lib_u:
                    candidates = recs
                    break
        if not candidates:
            return None
        # 1) exact symbol in lib
        for c in candidates:
            if str(c.get("symbol", "")) == sym:
                return str(c.get("lookup", ""))
        # 2) base+suffix (LM1117-5.0 -> LM1117DT-5.0)
        m = re.match(r"^([A-Za-z0-9]+?)(-\d.*)$", sym)
        if m:
            base, suffix = m.group(1), m.group(2)
            hits = [c for c in candidates if str(c.get("symbol", "")).startswith(base) and str(c.get("symbol", "")).endswith(suffix)]
            if hits:
                hits.sort(key=lambda x: len(str(x.get("symbol", ""))))
                return str(hits[0].get("lookup", ""))
        # 3) prefix in same lib
        if len(sym) >= 4:
            hits = [c for c in candidates if str(c.get("symbol", "")).startswith(sym) or sym.startswith(str(c.get("symbol", "")))]
            if hits:
                hits.sort(key=lambda x: len(str(x.get("symbol", ""))))
                return str(hits[0].get("lookup", ""))
        # 4) Strip common package suffixes (LLMs often append _TO220, _SOT23, etc.)
        stripped = re.sub(r'[_-](?:TO-?\d+|SOT-?\d+|SOIC|DIP|QFP\d*|TSSOP\d*|LQFP\d*|BGA\d*|MSOP\d*|DPAK|D2PAK|SC-?\d+)$', '', sym, flags=re.IGNORECASE)
        if stripped != sym and len(stripped) >= 3:
            for c in candidates:
                csym = str(c.get("symbol", ""))
                if csym.upper().startswith(stripped.upper()):
                    return str(c.get("lookup", ""))
        
        # 5) Strip internal package letters before a voltage suffix (e.g. LP2985AIM5-3.3 -> LP2985-3.3)
        stripped_mid = re.sub(r'^([A-Za-z]+[0-9]+)[A-Za-z0-9]*(-[0-9.]+)$', r'\1\2', sym)
        if stripped_mid != sym and len(stripped_mid) >= 3:
            for c in candidates:
                csym = str(c.get("symbol", ""))
                if csym.upper() == stripped_mid.upper() or csym.upper().startswith(stripped_mid.upper()):
                    return str(c.get("lookup", ""))
        
        return None

    # Bare symbols: search only the 4-char bucket (not the full records list).
    _ensure_derived_indexes(cache)
    lu = lookup.strip()
    if len(lu) < 4:
        return None
    key = lu[:4].upper()
    cand = (cache.get("__bare_sym_buckets") or {}).get(key) or []
    lu_u = lu.upper()
    hits = [
        r
        for r in cand
        if str(r.get("symbol", "")).upper().startswith(lu_u) or lu_u.startswith(str(r.get("symbol", "")).upper())
    ]
    if hits:
        hits.sort(key=lambda x: len(str(x.get("symbol", ""))))
        return str(hits[0].get("lookup", ""))
    return None


def search_symbol_candidates(
    query: str,
    cache: dict[str, Any] | None,
    *,
    limit: int = 12,
    lib: str | None = None,
) -> list[dict[str, str]]:
    """Return ranked valid symbol candidates from cache."""
    if not query or not cache:
        return []
    query_orig = query.strip()
    query = query_orig
    q_u = query.upper()
    if not q_u:
        return []

    candidates: list[dict[str, str]] = []
    _ensure_derived_indexes(cache)
    source: list[dict[str, str]] = []

    if lib:
        source = list((cache.get("by_lib") or {}).get(lib.strip()) or [])
    elif ":" in query:
        lib_hint, tail = query.split(":", 1)
        lib_hint = lib_hint.strip()
        tail = tail.strip()
        by_lib_raw = cache.get("by_lib") or {}
        if lib_hint:
            narrowed_list = by_lib_raw.get(lib_hint)
            if narrowed_list is None:
                lh_u = lib_hint.upper()
                for k_bl, recs in by_lib_raw.items():
                    if isinstance(k_bl, str) and k_bl.upper() == lh_u:
                        narrowed_list = recs
                        break
            if isinstance(narrowed_list, list) and narrowed_list:
                source = list(narrowed_list)
                if tail:
                    query = tail
                    q_u = query.upper()
            else:
                # Library hint was totally wrong (e.g. Connector_USB instead of Connector)
                # Fallback to unscoped query
                query = tail
                q_u = query.upper()
                if len(q_u) >= 4:
                    source = list((cache.get("__bare_sym_buckets") or {}).get(q_u[:4], []))
    else:
        # Unscoped query: scan one prefix bucket instead of all records.
        if len(q_u) >= 4:
            source = list((cache.get("__bare_sym_buckets") or {}).get(q_u[:4], []))
        else:
            source = []

    def score(rec: dict[str, str]) -> tuple[int, int]:
        sym = str(rec.get("symbol", ""))
        lookup = str(rec.get("lookup", ""))
        s_u = sym.upper()
        l_u = lookup.upper()
        if l_u == q_u or s_u == q_u:
            return (0, len(sym))
        if l_u.startswith(q_u) or s_u.startswith(q_u):
            return (1, len(sym))
        if q_u in l_u or q_u in s_u:
            return (2, len(sym))
        return (3, len(sym))

    for rec in source:
        sym = str(rec.get("symbol", ""))
        lookup = str(rec.get("lookup", ""))
        if not sym or not lookup:
            continue
        s_u = sym.upper()
        l_u = lookup.upper()
        if q_u in s_u or q_u in l_u or s_u.startswith(q_u) or l_u.startswith(q_u):
            candidates.append(rec)

    candidates.sort(key=score)
    return candidates[: max(1, min(limit, 50))]
