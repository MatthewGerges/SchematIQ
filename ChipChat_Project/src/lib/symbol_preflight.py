"""
Check LLM JSON components resolve to KiCad symbols (same rules as schematic_generator).
"""

from __future__ import annotations

import os

from src.lib import symbol_resolver
from src.lib.symbol_aliases import apply_symbol_alias, normalize_symbol_lookup

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CHIPCHAT_PROJECT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))


def _repo_root():
    return os.path.dirname(_CHIPCHAT_PROJECT)


def _custom_symbols_dir():
    return os.path.join(_repo_root(), "KICAD_Library", "Symbols")


def _official_symbols_dir():
    return os.path.join(_repo_root(), "KICAD_Library", "kicad-symbols")


def preview_resolve(symbol_lookup: str) -> tuple[bool, str]:
    """Return (ok, detail) — whether generation can embed this lookup string."""
    custom_dir = _custom_symbols_dir()
    official_dir = _official_symbols_dir()
    custom_path = os.path.join(custom_dir, f"{symbol_lookup}.kicad_sym")
    if os.path.isfile(custom_path):
        return True, f"custom file {os.path.basename(custom_path)}"

    if ":" in symbol_lookup:
        lib_name, sym_name = symbol_lookup.split(":", 1)
        packed = os.path.join(official_dir, f"{lib_name}.kicad_sym")
        if os.path.isfile(packed):
            names = set(symbol_resolver.list_top_level_symbols_in_packed(packed))
            if sym_name in names:
                return True, f"{lib_name}:{sym_name}"
            alt = symbol_resolver.resolve_in_packed_library(packed, sym_name)
            if alt:
                return True, f"{lib_name}:{sym_name} → {alt} (generic in-lib)"
            return False, f"symbol '{sym_name}' not in {lib_name}.kicad_sym"
        return False, f"library file {lib_name}.kicad_sym not found"

    resolved = symbol_resolver.resolve_symbol(symbol_lookup)
    if resolved:
        sym_name, kind, path = resolved
        where = os.path.basename(path) if kind == "packed" else "custom"
        return True, f"fuzzy → {sym_name} ({where})"
    return False, "no packed lib:sym and fuzzy resolve failed"


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
        ok, detail = preview_resolve(lookup)
        if not ok:
            errors.append(f"{ref}: '{raw}' → lookup '{lookup}' — {detail}")
        elif print_ok:
            print(f"  OK {ref}: '{raw}' → {lookup} ({detail})")
    return errors
