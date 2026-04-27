"""
Test script: verify official KiCad 9 libraries were cloned and symbols can be
placed on a schematic page using the existing kicad_api.

Picks a few symbols from different libraries (custom + official packed),
embeds them, places them on a blank schematic, saves to .kicad_sch + .kicad_pro
that you can open in KiCad to visually confirm.

Usage:
    cd Code
    source .venv/bin/activate
    python scripts/test_kicad_library.py
"""

import os
import sys
import uuid as uuid_mod

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import kicad_api, project_generator, symbol_resolver
from src.lib.kicad_library_paths import lib_prefix_from_unpacked_symbol_file, official_kicad_symbols_root, repo_root

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = repo_root()
KICAD_LIB = os.path.join(REPO_ROOT, "KICAD_Library")
CUSTOM_SYMBOLS = os.path.join(KICAD_LIB, "Symbols")
OFFICIAL_SYMBOLS = official_kicad_symbols_root() or ""
OFFICIAL_FOOTPRINTS = os.path.join(KICAD_LIB, "kicad-footprints")

OUTPUT_DIR = os.path.join(PROJECT_DIR, "generated", "library_test")
PROJECT_NAME = "library_test"
SCH_FILE = os.path.join(OUTPUT_DIR, f"{PROJECT_NAME}.kicad_sch")


def check_repos():
    """Verify library repos exist (quick sentinel check)."""
    print("=" * 60)
    print("  Library Verification")
    print("=" * 60)

    checks = [
        ("Custom symbols", CUSTOM_SYMBOLS, "Resistor.kicad_sym"),
        ("Official symbols (clone)", OFFICIAL_SYMBOLS, None),
        ("Official footprints", OFFICIAL_FOOTPRINTS, "Package_SO.pretty"),
    ]

    all_ok = True
    for label, path, sentinel in checks:
        if sentinel is None:
            if not path:
                ok = False
                sentinel_path = "(no official symbols root — clone kicad-symbols)"
            else:
                packed = os.path.join(path, "Timer.kicad_sym")
                unpacked = os.path.join(path, "Timer.kicad_symdir")
                ok = os.path.isdir(path) and (os.path.isfile(packed) or os.path.isdir(unpacked))
                sentinel_path = packed if os.path.isfile(packed) else unpacked
        else:
            sentinel_path = os.path.join(path, sentinel)
            ok = os.path.exists(sentinel_path)
        if ok:
            print(f"  OK: {label}")
        else:
            print(f"  MISSING: {label} — expected {sentinel_path}")
            all_ok = False

    print()
    return all_ok


def check_footprint(footprint_lib, footprint_name):
    """Check if a footprint .kicad_mod file exists."""
    fp_file = os.path.join(
        OFFICIAL_FOOTPRINTS, f"{footprint_lib}.pretty", f"{footprint_name}.kicad_mod"
    )
    return os.path.isfile(fp_file)


def main():
    if not check_repos():
        print("Some libraries are missing. See README for clone instructions.")
        sys.exit(1)

    # Test cases: mix of custom single-file symbols and official KiCad libraries
    # (packed ``.kicad_sym`` or unpacked ``.kicad_symdir`` from the GitLab clone).
    # We only *place* existing symbols on the page (embed + instance); we do not create new symbol graphics.
    test_symbols = [
        {
            "label": "NE555D (official Timer lib)",
            "lib_lookup": "Timer:NE555D",
            "footprint": ("Package_SO", "SOIC-8_3.9x4.9mm_P1.27mm"),
            "pins": ["1", "2", "3", "4", "5", "6", "7", "8"],
        },
        {
            "label": "AP1117-15 (official Regulator_Linear lib, base symbol)",
            "lib_lookup": "Regulator_Linear:AP1117-15",
            "footprint": ("Package_TO_SOT_SMD", "SOT-223-3_TabPin2"),
            "pins": ["1", "2", "3"],
        },
        {
            "label": "nRF5340-QKxx (official MCU_Nordic lib)",
            "lib_lookup": "MCU_Nordic:nRF5340-QKxx",
            "footprint": ("Package_DFN_QFN", "Nordic_AQFN-94-1EP_7x7mm_P0.4mm"),
            "pins": None,  # 94-pin BGA-style; optional pin list
        },
        {
            "label": "BME280 (custom lib)",
            "symbol_name": "BME280",
            "source": "custom",
            "footprint": None,
            "pins": ["1", "2", "3", "4", "5", "6", "7", "8"],
        },
        {
            "label": "Resistor (custom lib)",
            "symbol_name": "Resistor",
            "source": "custom",
            "footprint": None,
            "pins": ["1", "2"],
        },
        {
            "label": "Capacitor (custom lib)",
            "symbol_name": "Capacitor",
            "source": "custom",
            "footprint": None,
            "pins": ["1", "2"],
            "ref": "C1",
            "value": "100nF",
        },
    ]

    sheet_uuid = str(uuid_mod.uuid4())
    schematic = kicad_api.create_schematic_data(PROJECT_NAME, sheet_uuid)

    print("=" * 60)
    print("  Placing Test Symbols")
    print("=" * 60)

    x_pos = 120.0
    y_start = 50.0
    y_spacing = 70.0
    success_count = 0

    for i, sym in enumerate(test_symbols):
        print(f"\n--- {sym['label']} ---")

        lookup = sym.get("lib_lookup")
        if lookup:
            resolved = symbol_resolver.resolve_symbol(lookup)
            if not resolved:
                print(f"  FAIL: could not resolve {lookup!r} (clone kicad-symbols?)")
                continue
            sym_name, kind, path = resolved
            if kind == "packed":
                lib_id = kicad_api.embed_symbol_from_packed_lib(schematic, sym_name, path)
            elif kind == "unpacked_single":
                lib_id = kicad_api.embed_symbol_from_file(
                    schematic,
                    sym_name,
                    library_path=path,
                    lib_prefix=lib_prefix_from_unpacked_symbol_file(path),
                )
            else:
                print(f"  FAIL: unexpected resolution kind {kind!r} for {lookup!r}")
                continue
        else:
            lib_id = kicad_api.embed_symbol_from_file(
                schematic, sym["symbol_name"], library_path=CUSTOM_SYMBOLS
            )

        if not lib_id:
            print(f"  FAIL: could not embed")
            continue

        pos_y = y_start + i * y_spacing
        ref = sym.get("ref") or f"U{i + 1}"
        value = sym.get("value") or sym.get("symbol_name") or (lookup.split(":", 1)[1] if lookup else "")
        pins = sym.get("pins")
        kicad_api.place_component(
            schematic, lib_id, ref, value,
            (x_pos, pos_y), angle=0,
            footprint="", pins=pins,
        )
        success_count += 1

        if sym["footprint"]:
            fp_lib, fp_name = sym["footprint"]
            fp_ok = check_footprint(fp_lib, fp_name)
            print(f"  Footprint {fp_lib}/{fp_name}: {'OK' if fp_ok else 'MISSING'}")

    # Save schematic + project
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    kicad_api.save_schematic(schematic, SCH_FILE)
    project_generator.generate_project_file(PROJECT_NAME, OUTPUT_DIR)
    pro_file = os.path.join(OUTPUT_DIR, f"{PROJECT_NAME}.kicad_pro")

    print("\n" + "=" * 60)
    print(f"  Results: {success_count}/{len(test_symbols)} symbols placed")
    print(f"  Schematic: {SCH_FILE}")
    print(f"  Project:   {pro_file}")
    print(f"  Open the .kicad_pro in KiCad to verify.")
    print("=" * 60)


if __name__ == "__main__":
    main()
