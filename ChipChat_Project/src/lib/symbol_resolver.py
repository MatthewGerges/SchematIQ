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

    for (sym_name, kind, path) in index:
        if sym_name == part_name:
            return (sym_name, kind, path)

    for (sym_name, kind, path) in index:
        if sym_name.startswith(part_name) or part_name.startswith(sym_name):
            return (sym_name, kind, path)

    prefix = part_name[:6] if len(part_name) >= 6 else part_name
    if len(prefix) < 4:
        return None
    for (sym_name, kind, path) in index:
        if sym_name.startswith(prefix) or prefix.startswith(sym_name[:6]):
            return (sym_name, kind, path)

    return None


def get_custom_symbols_path():
    return CUSTOM_SYMBOLS_DIR


def get_official_symbols_path():
    return OFFICIAL_SYMBOLS_DIR
