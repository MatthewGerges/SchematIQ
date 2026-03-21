"""
Resolve a component/part name to a KiCad symbol in custom or official libraries.

When the LLM outputs a part name that is not in components.json, we try to find
a matching symbol by:
  - Exact match (e.g. "nRF5340-QKxx")
  - Prefix match (e.g. "LM1117" matches "LM1117DT-3.3")
  - First-6-chars match (tape/reel and package suffixes often differ after the base part)
"""

import os
import re

# Repo layout: ChipChat_Project/src/lib/symbol_resolver.py -> repo root is parent of ChipChat_Project
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_SCRIPT_DIR)))
KICAD_LIB = os.path.join(_REPO_ROOT, "KICAD_Library")
CUSTOM_SYMBOLS_DIR = os.path.join(KICAD_LIB, "Symbols")
OFFICIAL_SYMBOLS_DIR = os.path.join(KICAD_LIB, "kicad-symbols")

# (symbol_name, "custom", path_to_dir) or (symbol_name, "packed", path_to_.kicad_sym)
_symbol_index = None

# Avoid matching single-letter symbols (e.g. Simulation_SPICE "D") to "Diode:..." via prefix rules
_MIN_SYM_LEN_FUZZY = 4


def _top_level_symbol_names_from_packed_file(file_path):
    """Return list of top-level symbol names from a packed .kicad_sym file.
    Skips sub-symbols like Foo_0_1, Foo_1_1.
    """
    names = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r'^\t\(symbol "([^"]+)"\s*$', line)
                if not m:
                    continue
                name = m.group(1)
                if "_" in name:
                    parts = name.rsplit("_", 2)
                    if len(parts) == 3 and parts[-2].isdigit() and parts[-1].isdigit():
                        continue
                names.append(name)
    except (OSError, UnicodeDecodeError):
        pass
    return names


def _build_index():
    """Build a flat index: list of (symbol_name, kind, path)."""
    global _symbol_index
    if _symbol_index is not None:
        return _symbol_index

    index = []

    if os.path.isdir(CUSTOM_SYMBOLS_DIR):
        for f in os.listdir(CUSTOM_SYMBOLS_DIR):
            if f.endswith(".kicad_sym"):
                name = f[:- len(".kicad_sym")]
                index.append((name, "custom", CUSTOM_SYMBOLS_DIR))

    if os.path.isdir(OFFICIAL_SYMBOLS_DIR):
        for f in os.listdir(OFFICIAL_SYMBOLS_DIR):
            if f.endswith(".kicad_sym"):
                path = os.path.join(OFFICIAL_SYMBOLS_DIR, f)
                for name in _top_level_symbol_names_from_packed_file(path):
                    index.append((name, "packed", path))

    _symbol_index = index
    return index


def list_top_level_symbols_in_packed(packed_lib_path):
    """Return top-level symbol names in a packed .kicad_sym (for validation)."""
    if not packed_lib_path or not os.path.isfile(packed_lib_path):
        return []
    return _top_level_symbol_names_from_packed_file(packed_lib_path)


def resolve_in_packed_library(packed_lib_path, requested_symbol):
    """Pick a symbol name inside one .kicad_sym file when the LLM name is wrong.

    Handles common generics (NPN, PNP) inside Transistor_BJT; exact name if present.
    Returns symbol name string or None.
    """
    if not packed_lib_path or not os.path.isfile(packed_lib_path):
        return None
    names = set(_top_level_symbol_names_from_packed_file(packed_lib_path))
    req = (requested_symbol or "").strip()
    if not req:
        return None
    if req in names:
        return req
    u = req.upper()
    if u == "NPN":
        for cand in (
            "Q_NPN_BCE",
            "Q_NPN_BEC",
            "Q_NPN_CBE",
            "Q_NPN_EBC",
            "Q_NPN_ECB",
            "Q_NPN_CEB",
        ):
            if cand in names:
                return cand
    if u == "PNP":
        for cand in (
            "Q_PNP_BCE",
            "Q_PNP_BEC",
            "Q_PNP_CBE",
            "Q_PNP_EBC",
            "Q_PNP_ECB",
            "Q_PNP_CEB",
        ):
            if cand in names:
                return cand
    return None


def resolve_symbol(part_name):
    """Find the best matching symbol for a part name (e.g. from LLM output).

    Returns:
        (symbol_name, "custom", library_dir) or (symbol_name, "packed", library_file_path)
        or None if no match.
    """
    if not part_name or not part_name.strip():
        return None

    part_name = part_name.strip()
    index = _build_index()

    # "Library:Symbol" — global fuzzy match is unsafe (e.g. Diode:LED → SPICE "D").
    # Callers should use exact packed-lib embed + resolve_in_packed_library first.
    search_token = part_name
    if ":" in part_name:
        search_token = part_name.split(":", 1)[1].strip()
        if not search_token:
            return None

    for (sym_name, kind, path) in index:
        if sym_name == part_name or sym_name == search_token:
            return (sym_name, kind, path)

    for (sym_name, kind, path) in index:
        if len(sym_name) < _MIN_SYM_LEN_FUZZY:
            continue
        if sym_name.startswith(search_token) or search_token.startswith(sym_name):
            return (sym_name, kind, path)

    prefix = search_token[:6] if len(search_token) >= 6 else search_token
    if len(prefix) < 4:
        return None
    for (sym_name, kind, path) in index:
        if len(sym_name) < _MIN_SYM_LEN_FUZZY:
            continue
        sym6 = sym_name[:6] if len(sym_name) >= 6 else sym_name
        if len(sym6) < 4:
            continue
        if sym_name.startswith(prefix) or prefix.startswith(sym6):
            return (sym_name, kind, path)

    return None


def get_custom_symbols_path():
    return CUSTOM_SYMBOLS_DIR


def get_official_symbols_path():
    return OFFICIAL_SYMBOLS_DIR
