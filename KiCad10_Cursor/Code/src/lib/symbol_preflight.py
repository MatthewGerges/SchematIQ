"""
Check LLM JSON components resolve to KiCad symbols (same rules as schematic_generator).
"""

from __future__ import annotations

import os

from src.lib import symbol_resolver
from src.lib.kicad_library_paths import (
    find_unpacked_symbol_file,
    official_kicad_symbols_root,
    official_library_packed_path,
    official_library_symdir_path,
)
from src.lib.symbol_aliases import apply_symbol_alias, normalize_symbol_lookup

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))


def _repo_root():
    return os.path.dirname(_CODE_ROOT)


def _custom_symbols_dir():
    return os.path.join(_repo_root(), "KICAD_Library", "Symbols")


def _official_symbols_dir():
    return official_kicad_symbols_root() or os.path.join(_repo_root(), "KICAD_Library", "kicad-symbols")


def _min_pin_count_from_connections(comp: dict) -> int:
    """Same heuristic as schematic_generator (blocks bad fuzzy matches)."""
    conns = comp.get("connections") or []
    max_n = 0
    for c in conns:
        p = str(c.get("pin", "")).strip()
        if p.isdigit():
            max_n = max(max_n, int(p))
    return max(max_n, len(conns))


def preview_resolve(symbol_lookup: str, min_pin_count: int | None = None) -> tuple[bool, str]:
    """Return (ok, detail) — whether generation can embed this lookup string.

    If *min_pin_count* is set, fuzzy resolution uses the same pin-count guard as
    ``schematic_generator`` (avoids approving a 1-pin stub for a 10-pin JSON).
    """
    custom_dir = _custom_symbols_dir()
    custom_path = os.path.join(custom_dir, f"{symbol_lookup}.kicad_sym")
    if os.path.isfile(custom_path):
        return True, f"custom file {os.path.basename(custom_path)}"

    if ":" in symbol_lookup:
        lib_name, sym_name = symbol_lookup.split(":", 1)
        lib_name, sym_name = lib_name.strip(), sym_name.strip()
        packed = official_library_packed_path(lib_name)
        if packed and os.path.isfile(packed):
            names = set(symbol_resolver.list_top_level_symbols_in_packed(packed))
            if sym_name in names:
                return True, f"{lib_name}:{sym_name}"
            alt = symbol_resolver.resolve_in_packed_library(packed, sym_name)
            if alt:
                return True, f"{lib_name}:{sym_name} → {alt} (generic in-lib)"
            return False, f"symbol '{sym_name}' not in {lib_name}.kicad_sym"
        symdir = official_library_symdir_path(lib_name)
        if symdir:
            sf = find_unpacked_symbol_file(symdir, sym_name)
            if sf:
                return True, f"{lib_name}:{sym_name} (unpacked {os.path.basename(sf)})"
            return False, f"symbol '{sym_name}' not found under {lib_name}.kicad_symdir"
        return False, f"no {lib_name}.kicad_sym or {lib_name}.kicad_symdir in official library path"

    resolved = symbol_resolver.resolve_symbol(symbol_lookup, min_pin_count=min_pin_count)
    if resolved:
        sym_name, kind, path = resolved
        if kind == "packed":
            where = os.path.basename(path)
        elif kind == "unpacked_single":
            where = os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path)
        else:
            where = "custom"
        return True, f"fuzzy → {sym_name} ({where})"
    return False, "no packed lib:sym and fuzzy resolve failed"


def find_unresolved_components(data: dict) -> list[dict]:
    """
    Return structured entries for components whose ``part`` does not resolve.

    Each item: ``ref``, ``part``, ``lookup``, ``detail``, ``min_pin_count``, ``sheet``.
    """
    out: list[dict] = []
    sheets = {s["name"] for s in data.get("sheets", [])}
    for comp in data.get("components", []):
        sheet = comp.get("sheet", "")
        if sheets and sheet and sheet not in sheets:
            continue
        raw = comp.get("part", "")
        ref = comp.get("ref", "?")
        after_alias = apply_symbol_alias(raw)
        lookup = normalize_symbol_lookup(after_alias)
        min_pins = _min_pin_count_from_connections(comp)
        ok, detail = preview_resolve(lookup, min_pin_count=min_pins or None)
        if not ok:
            out.append(
                {
                    "ref": ref,
                    "part": raw,
                    "lookup": lookup,
                    "detail": detail,
                    "min_pin_count": min_pins,
                    "sheet": sheet,
                }
            )
    return out


def validate_components_in_llm_data(data: dict, print_ok: bool = False) -> list[str]:
    """
    Return a list of error messages (empty if all components resolve).
    """
    errors: list[str] = []
    sheets = {s["name"] for s in data.get("sheets", [])}
    for comp in data.get("components", []):
        sheet = comp.get("sheet", "")
        if sheets and sheet and sheet not in sheets:
            continue
        raw = comp.get("part", "")
        ref = comp.get("ref", "?")
        after_alias = apply_symbol_alias(raw)
        lookup = normalize_symbol_lookup(after_alias)
        min_pins = _min_pin_count_from_connections(comp)
        ok, detail = preview_resolve(lookup, min_pin_count=min_pins or None)
        if not ok:
            errors.append(f"{ref}: '{raw}' → lookup '{lookup}' — {detail}")
        elif print_ok:
            print(f"  OK {ref}: '{raw}' → {lookup} ({detail})")
    return errors
