"""
Resolve a component/part name to a KiCad symbol in custom or official libraries.

When the LLM outputs a part name that does not match a library symbol directly, we try to find
a matching symbol by:
  - Exact match (e.g. "nRF5340-QKxx")
  - Prefix match (e.g. "LM1117" matches "LM1117DT-3.3")
  - First-6-chars match (tape/reel and package suffixes often differ after the base part)
"""

import os
import re

from src.lib.kicad_library_paths import (
    find_unpacked_symbol_file,
    official_kicad_symbols_root,
    official_library_packed_path,
    official_library_symdir_path,
    lib_prefix_from_unpacked_symbol_file,
)

# Repo layout: Code/src/lib/symbol_resolver.py -> repo root is parent of Code/
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_SCRIPT_DIR)))
KICAD_LIB = os.path.join(_REPO_ROOT, "KICAD_Library")
CUSTOM_SYMBOLS_DIR = os.path.join(KICAD_LIB, "Symbols")

# (symbol_name, "custom", path_to_dir) or (symbol_name, "packed", path_to_.kicad_sym)
_symbol_index = None

# Avoid matching single-letter symbols (e.g. Simulation_SPICE "D") to "Diode:..." via prefix rules
_MIN_SYM_LEN_FUZZY = 4


def reset_symbol_index() -> None:
    """Clear cached index (e.g. after cloning kicad-symbols)."""
    global _symbol_index
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

    official_root = official_kicad_symbols_root()
    if official_root and os.path.isdir(official_root):
        for f in os.listdir(official_root):
            path = os.path.join(official_root, f)
            if f.endswith(".kicad_sym") and os.path.isfile(path):
                for name in _top_level_symbol_names_from_packed_file(path):
                    index.append((name, "packed", path))
            elif f.endswith(".kicad_symdir") and os.path.isdir(path):
                try:
                    for fn in os.listdir(path):
                        if not fn.endswith(".kicad_sym"):
                            continue
                        fp = os.path.join(path, fn)
                        if not os.path.isfile(fp):
                            continue
                        for name in _top_level_symbol_names_from_packed_file(fp):
                            index.append((name, "unpacked_single", fp))
                except OSError:
                    pass

    _symbol_index = index
    return index


def list_top_level_symbols_in_packed(packed_lib_path):
    """Return top-level symbol names in a packed .kicad_sym (for validation)."""
    if not packed_lib_path or not os.path.isfile(packed_lib_path):
        return []
    return _top_level_symbol_names_from_packed_file(packed_lib_path)


def _count_pin_entries_in_symbol_block(block):
    """Count (pin ... entries in a symbol block."""
    n = 0
    for line in block.splitlines():
        if "\t\t(pin " in line or line.strip().startswith("(pin "):
            n += 1
    return n


def _extract_symbol_block(content, symbol_name):
    """Return the s-expression text for (symbol "symbol_name" ...), or None."""
    needle = f'(symbol "{symbol_name}"'
    idx = content.find(needle)
    if idx < 0:
        return None
    depth = 0
    for i in range(idx, len(content)):
        c = content[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return content[idx : i + 1]
    return None


def count_pins_in_symbol(symbol_name, kind, path):
    """Return number of pins for a top-level symbol (for rejecting bad fuzzy matches)."""
    if kind == "packed" and path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return 0
        block = _extract_symbol_block(content, symbol_name)
        if not block:
            return 0
        return _count_pin_entries_in_symbol_block(block)
    if kind == "custom" and path:
        fp = os.path.join(path, f"{symbol_name}.kicad_sym")
        if os.path.isfile(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    c = f.read()
            except OSError:
                return 0
            return _count_pin_entries_in_symbol_block(c)
    if kind == "unpacked_single" and path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return 0
        block = _extract_symbol_block(content, symbol_name)
        if not block:
            return 0
        return _count_pin_entries_in_symbol_block(block)
    return 0


def resolve_in_packed_library(packed_lib_path, requested_symbol):
    """Pick a symbol name inside one .kicad_sym file when the LLM name is wrong.

    Handles common generics (NPN, PNP) inside Transistor_BJT; exact name if present.
    Also handles missing package codes: "LM1117-5.0" → "LM1117DT-5.0".
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

    # Fuzzy: handle missing package codes. Split on the first hyphen that
    # precedes a digit (e.g. "LM1117-5.0" → base="LM1117", suffix="-5.0").
    # Then find any symbol starting with the base and ending with the suffix.
    m = re.match(r'^([A-Za-z0-9]+?)(-\d.*)$', req)
    if m:
        base, suffix = m.group(1), m.group(2)
        # Prefer shortest insertion (fewest extra chars) → likely the default package.
        candidates = sorted(
            (n for n in names if n.startswith(base) and n.endswith(suffix)),
            key=len,
        )
        if candidates:
            return candidates[0]

    # Broader prefix: any symbol that starts with the same base (before first dash).
    base_part = req.split("-", 1)[0] if "-" in req else req
    if len(base_part) >= 4:
        candidates = sorted(
            (n for n in names if n.startswith(base_part)),
            key=len,
        )
        if candidates:
            return candidates[0]

    return None


def _resolve_in_symdir(symdir: str, sym: str, min_pin_count):
    """First matching symbol file in *symdir* where ``resolve_in_packed_library`` accepts *sym*."""
    if not symdir or not os.path.isdir(symdir):
        return None
    try:
        for fn in sorted(os.listdir(symdir)):
            if not fn.endswith(".kicad_sym"):
                continue
            candidate = os.path.join(symdir, fn)
            n = resolve_in_packed_library(candidate, sym)
            if n and _ok_pin_count(n, "unpacked_single", candidate, min_pin_count):
                return (n, "unpacked_single", candidate)
    except OSError:
        pass
    return None


def fuzzy_resolve_symbol_name_in_library(lib_name: str, sym_hint: str) -> str | None:
    """Return a top-level symbol name inside official *lib_name* for a fuzzy *sym_hint*, or None."""
    lib_name = (lib_name or "").strip()
    sym_hint = (sym_hint or "").strip()
    if not lib_name or not sym_hint:
        return None
    packed = official_library_packed_path(lib_name)
    if packed:
        return resolve_in_packed_library(packed, sym_hint)
    symdir = official_library_symdir_path(lib_name)
    if not symdir:
        return None
    hit = _resolve_in_symdir(symdir, sym_hint, None)
    return hit[0] if hit else None


def _ok_pin_count(sym_name, kind, path, min_pin_count):
    if min_pin_count is None or min_pin_count <= 0:
        return True
    n = count_pins_in_symbol(sym_name, kind, path)
    return n >= min_pin_count


def resolve_symbol(part_name, min_pin_count=None):
    """Find the best matching symbol for a part name (e.g. from LLM output).

    If *min_pin_count* is set, fuzzy matches (prefix / first-6-char) are rejected
    when the symbol has fewer pins — avoids ``Conn_02x05_*`` resolving to
    ``Conn_01x01_Pin`` because both start with ``Conn_``.

    Returns:
        (symbol_name, "custom", library_dir) or (symbol_name, "packed", library_file_path)
        or None if no match.
    """
    if not part_name or not part_name.strip():
        return None

    part_name = part_name.strip()

    # Explicit ``Library:Symbol`` — resolve against cloned official tree first
    # (packed ``Lib.kicad_sym`` or unpacked ``Lib.kicad_symdir/*.kicad_sym``).
    if ":" in part_name:
        lib, sym = part_name.split(":", 1)
        lib, sym = lib.strip(), sym.strip()
        if lib and sym:
            packed = official_library_packed_path(lib)
            if packed:
                resolved = resolve_in_packed_library(packed, sym) or sym
                if _ok_pin_count(resolved, "packed", packed, min_pin_count):
                    return (resolved, "packed", packed)
            symdir = official_library_symdir_path(lib)
            if symdir:
                hit = _resolve_in_symdir(symdir, sym, min_pin_count)
                if hit:
                    return hit

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
            # Exact match: always use it (pin-count filter is for fuzzy only).
            return (sym_name, kind, path)

    for (sym_name, kind, path) in index:
        if len(sym_name) < _MIN_SYM_LEN_FUZZY:
            continue
        if sym_name.startswith(search_token) or search_token.startswith(sym_name):
            if _ok_pin_count(sym_name, kind, path, min_pin_count):
                return (sym_name, kind, path)

    # Third fuzzy pass: prefix match. Use an 8-char prefix so "Conn_02x05_*" does not
    # collide with "Conn_01x01_*" (a 6-char "Conn_0" matches almost every Conn_*).
    # If the LLM adds a suffix with "_" (e.g. nRF5340_SoC), also try the stem
    # (nRF5340) so we still match nRF5340-QKxx — search_token[:8] alone is "nRF5340_S"
    # which does not match "nRF5340-Q…".
    prefix_candidates = []
    if "_" in search_token:
        stem = search_token.split("_", 1)[0]
        if len(stem) >= 6:
            prefix_candidates.append(stem[:8] if len(stem) >= 8 else stem)
    if len(search_token) >= 8:
        prefix_candidates.append(search_token[:8])
    elif len(search_token) >= 4:
        prefix_candidates.append(search_token)

    seen = set()
    for prefix in prefix_candidates:
        if prefix in seen or len(prefix) < 4:
            continue
        seen.add(prefix)
        plen = len(prefix)
        for (sym_name, kind, path) in index:
            if len(sym_name) < _MIN_SYM_LEN_FUZZY:
                continue
            sym_p = sym_name[:plen] if len(sym_name) >= plen else sym_name
            if len(sym_p) < 4:
                continue
            if sym_name.startswith(prefix) or prefix.startswith(sym_p):
                if _ok_pin_count(sym_name, kind, path, min_pin_count):
                    return (sym_name, kind, path)

    # Fourth pass: base+suffix match for part numbers with package codes.
    # E.g. "LM1117-5.0" → base "LM1117", suffix "-5.0" → matches "LM1117DT-5.0".
    m = re.match(r'^([A-Za-z0-9]+?)(-\d.*)$', search_token)
    if m:
        base, suffix = m.group(1), m.group(2)
        if len(base) >= 4:
            candidates = [
                (sym_name, kind, path)
                for sym_name, kind, path in index
                if sym_name.startswith(base) and sym_name.endswith(suffix)
                and _ok_pin_count(sym_name, kind, path, min_pin_count)
            ]
            if candidates:
                candidates.sort(key=lambda t: len(t[0]))
                return candidates[0]

    return None


def list_lib_colon_symbols():
    """Return every indexed symbol as a lookup string.

    Packed libraries become ``LibraryName:SymbolName`` (matches KiCad). Custom
    single-file symbols in ``KICAD_Library/Symbols`` are listed as the bare
    symbol filename (no ``:``), which is how ``schematic_generator`` resolves
    them.

    Used by the LLM symbol-repair pass to validate suggestions and to build a
    ranked candidate list.
    """
    out = []
    index = _build_index()
    for sym_name, kind, path in index:
        if kind == "packed":
            lib = os.path.splitext(os.path.basename(path))[0]
            out.append(f"{lib}:{sym_name}")
        elif kind == "unpacked_single":
            lib = lib_prefix_from_unpacked_symbol_file(path)
            out.append(f"{lib}:{sym_name}")
        else:
            out.append(sym_name)
    out.sort()
    return out


def get_custom_symbols_path():
    return CUSTOM_SYMBOLS_DIR


def get_official_symbols_path():
    return official_kicad_symbols_root() or os.path.join(KICAD_LIB, "kicad-symbols")
