"""
Resolve schematic ``Footprint`` fields (``LibNick:FootprintName``) using symbol
defaults and small deterministic fallbacks. Validates against the official
``kicad-footprints`` clone (``.pretty`` trees).
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any

from src.lib.kicad_library_paths import footprint_mod_path, footprint_string_resolves

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
_CONFIG_PATH = os.path.join(_CODE_ROOT, "config", "footprint_defaults.json")


@lru_cache(maxsize=1)
def _passive_defaults() -> dict[str, str]:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return dict(data.get("passive_footprints") or {})
    except (OSError, json.JSONDecodeError):
        return {}


def extract_footprint_property_from_symbol_block(block: str) -> str:
    """Return Footprint property value from a single symbol definition string."""
    m = re.search(r'\(property\s+"Footprint"\s+"([^"]*)"', block)
    return m.group(1).strip() if m else ""


def extract_footprint_from_embedded_lib(schematic_data: dict[str, Any], lib_id: str) -> str:
    """Read default Footprint from ``lib_symbols`` entry matching *lib_id*."""
    for sym_def in schematic_data.get("lib_symbols") or []:
        m = re.search(r'\(symbol\s+"([^"]+)"', sym_def)
        if not m or m.group(1) != lib_id:
            continue
        return extract_footprint_property_from_symbol_block(sym_def)
    return ""


def _fuzzy_footprint_in_lib(lib: str, hint: str) -> str | None:
    """If ``hint`` is a footprint name without lib prefix, find best ``.kicad_mod`` in *lib*.pretty."""
    if not hint or ":" in hint:
        return None
    from src.lib.kicad_library_paths import official_kicad_footprints_root

    root = official_kicad_footprints_root()
    if not root:
        return None
    pretty = os.path.join(root, f"{lib}.pretty")
    if not os.path.isdir(pretty):
        return None
    hint_u = hint.upper()
    try:
        names = [fn[:-10] for fn in os.listdir(pretty) if fn.endswith(".kicad_mod")]
    except OSError:
        return None
    if hint in names:
        return f"{lib}:{hint}"
    # prefix / contains match
    candidates = sorted(
        (n for n in names if hint_u in n.upper() or n.upper().startswith(hint_u[: min(6, len(hint_u))])),
        key=len,
    )
    if candidates:
        return f"{lib}:{candidates[0]}"
    return None


def resolve_footprint_for_instance(
    *,
    lib_id: str,
    sym_props_footprint: str,
    schematic_data: dict[str, Any] | None,
    passive_type: str | None = None,
) -> str:
    """
    Return a ``Lib:Footprint`` string for a placed symbol.

    Order: non-empty symbol default if it resolves → passive config → fuzzy in
    inferred lib from default → empty string.
    """
    # 1) From extracted props, then embedded lib (when *schematic_data* is provided)
    candidates: list[str] = []
    s0 = (sym_props_footprint or "").strip()
    if s0:
        candidates.append(s0)
    if schematic_data is not None:
        e0 = extract_footprint_from_embedded_lib(schematic_data, lib_id).strip()
        if e0:
            candidates.append(e0)
    for c in candidates:
        if c and footprint_string_resolves(c):
            return c

    # 2) Passive defaults (Device:R etc.)
    if passive_type:
        ptype = passive_type.strip()
        d = _passive_defaults()
        if ptype in d:
            fp = d[ptype].strip()
            if fp and footprint_string_resolves(fp):
                return fp

    # 3) Fuzzy: symbol had Lib:FP with missing mod — try same lib
    raw = ""
    for c in candidates:
        cc = (c or "").strip()
        if ":" in cc:
            raw = cc
            break
    if raw and ":" in raw:
        lib, name = raw.split(":", 1)
        lib, name = lib.strip(), name.strip()
        alt = _fuzzy_footprint_in_lib(lib, name)
        if alt and footprint_string_resolves(alt):
            return alt

    # 4) Empty default from symbol — try fuzzy on passive default's lib
    if passive_type and passive_type in _passive_defaults():
        fp0 = _passive_defaults()[passive_type]
        if ":" in fp0:
            lib0, name0 = fp0.split(":", 1)
            alt = _fuzzy_footprint_in_lib(lib0.strip(), name0.strip())
            if alt and footprint_string_resolves(alt):
                return alt

    return (sym_props_footprint or "").strip()
