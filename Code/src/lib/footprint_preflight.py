"""
Validate that resolved schematic footprints exist under the official
``kicad-footprints`` clone (same resolution order as schematic_generator).
"""

from __future__ import annotations

import os

from src.lib import kicad_api, symbol_resolver
from src.lib.footprint_resolver import (
    extract_footprint_property_from_symbol_block,
    resolve_footprint_for_instance,
)
from src.lib.kicad_library_paths import (
    find_unpacked_symbol_file,
    footprint_string_resolves,
    official_kicad_footprints_root,
    official_library_packed_path,
    official_library_symdir_path,
)
from src.lib.symbol_aliases import apply_symbol_alias, normalize_symbol_lookup
from src.lib.symbol_preflight import _custom_symbols_dir, _min_pin_count_from_connections, preview_resolve


def _read_default_footprint_from_lookup(lookup: str, min_pin_count: int | None) -> str:
    """Return the symbol file's default ``Footprint`` property, or ``""``."""
    custom_dir = _custom_symbols_dir()
    custom_path = os.path.join(custom_dir, f"{lookup}.kicad_sym")
    if os.path.isfile(custom_path):
        with open(custom_path, encoding="utf-8") as f:
            content = f.read()
        return extract_footprint_property_from_symbol_block(content)

    if ":" in lookup:
        lib_name, sym_name = lookup.split(":", 1)
        lib_name, sym_name = lib_name.strip(), sym_name.strip()
        packed = official_library_packed_path(lib_name)
        if packed and os.path.isfile(packed):
            with open(packed, encoding="utf-8") as f:
                content = f.read()
            alt = symbol_resolver.resolve_in_packed_library(packed, sym_name) or sym_name
            block = kicad_api.get_symbol_block(content, alt)
            return extract_footprint_property_from_symbol_block(block or "") if block else ""
        symdir = official_library_symdir_path(lib_name)
        if symdir:
            sf = find_unpacked_symbol_file(symdir, sym_name)
            if sf:
                with open(sf, encoding="utf-8") as f:
                    content = f.read()
                return extract_footprint_property_from_symbol_block(content)
        return ""

    resolved = symbol_resolver.resolve_symbol(lookup, min_pin_count=min_pin_count or 0)
    if not resolved:
        return ""
    sym_name, kind, path = resolved
    if kind == "custom":
        sf = os.path.join(path, f"{sym_name}.kicad_sym")
        if os.path.isfile(sf):
            with open(sf, encoding="utf-8") as f:
                return extract_footprint_property_from_symbol_block(f.read())
        return ""
    if kind == "packed":
        with open(path, encoding="utf-8") as f:
            content = f.read()
        block = kicad_api.get_symbol_block(content, sym_name)
        return extract_footprint_property_from_symbol_block(block or "") if block else ""
    if kind == "unpacked_single":
        with open(path, encoding="utf-8") as f:
            content = f.read()
        return extract_footprint_property_from_symbol_block(content)
    return ""


def _resolved_lib_id_for_lookup(lookup: str, min_pin_count: int | None) -> str:
    """Return ``Lib:Sym`` form used in schematics (best-effort for resolver / fuzzy)."""
    if ":" in lookup:
        return lookup.strip()
    resolved = symbol_resolver.resolve_symbol(lookup, min_pin_count=min_pin_count or 0)
    if not resolved:
        return lookup.strip()
    sym_name, kind, path = resolved
    if kind == "custom":
        return f"SchematIQ:{sym_name}"
    if kind == "packed":
        nick = os.path.splitext(os.path.basename(path))[0]
        return f"{nick}:{sym_name}"
    if kind == "unpacked_single":
        parent = os.path.basename(os.path.dirname(path))
        if parent.endswith(".kicad_symdir"):
            nick = parent[: -len(".kicad_symdir")]
            return f"{nick}:{sym_name}"
        return f"{os.path.basename(path).replace('.kicad_sym', '')}:{sym_name}"
    nick = os.path.basename(path)
    return f"{nick}:{sym_name}"


def validate_footprints_in_llm_data(data: dict, print_ok: bool = False) -> list[str]:
    """
    Return error messages for components whose resolved ``Footprint`` does not
    exist under ``kicad-footprints``. Skips rows that fail symbol resolution
    (handled by ``validate_components_in_llm_data``).
    """
    if not official_kicad_footprints_root():
        if print_ok:
            print("  (footprint validate) No kicad-footprints clone; skipping footprint checks.")
        return []

    errors: list[str] = []
    sheets = {s["name"] for s in data.get("sheets", [])}

    for comp in data.get("components", []):
        sheet = comp.get("sheet", "")
        if sheets and sheet and sheet not in sheets:
            continue
        raw = comp.get("part", "")
        ref = comp.get("ref", "?")
        lookup = normalize_symbol_lookup(apply_symbol_alias(raw))
        min_pins = _min_pin_count_from_connections(comp)
        ok, _ = preview_resolve(lookup, min_pin_count=min_pins or None)
        if not ok:
            continue
        fp0 = _read_default_footprint_from_lookup(lookup, min_pins or None)
        lib_id = _resolved_lib_id_for_lookup(lookup, min_pins or None)
        fp = resolve_footprint_for_instance(
            lib_id=lib_id,
            sym_props_footprint=fp0,
            schematic_data=None,
            passive_type=None,
        )
        if fp and not footprint_string_resolves(fp):
            errors.append(f"{ref}: footprint '{fp}' (from '{lookup}') — no matching .kicad_mod in kicad-footprints")
        elif print_ok and fp:
            print(f"  OK footprint {ref}: {fp}")

    passive_type_map = {
        "R": "R",
        "C": "C",
        "L": "L",
        "FB": "FB",
        "D": "D",
        "Diode": "Diode",
    }
    for p in data.get("passives", []):
        sheet = p.get("sheet", "")
        if sheets and sheet and sheet not in sheets:
            continue
        ref = p.get("ref", "?")
        ptype = str(p.get("type", "")).strip()
        pkey = passive_type_map.get(ptype, ptype)
        if ptype.lower() in ("diode", "d_schottky", "schottky", "schottky_diode", "rectifier"):
            pkey = "Diode"
        fp = resolve_footprint_for_instance(
            lib_id="Device:R",
            sym_props_footprint="",
            schematic_data=None,
            passive_type=pkey,
        )
        if fp and not footprint_string_resolves(fp):
            errors.append(f"{ref}: passive footprint '{fp}' — no matching .kicad_mod in kicad-footprints")
        elif print_ok and fp:
            print(f"  OK footprint passive {ref}: {fp}")

    return errors
