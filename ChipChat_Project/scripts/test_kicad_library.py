"""
Test script: verify official KiCad libraries were cloned and symbols can be
placed on a schematic page using the existing kicad_api.

Picks a few symbols from different libraries (custom + official), embeds them,
places them on a blank schematic, and saves to a .kicad_sch file you can open
in KiCad to visually confirm.

Usage:
    cd ChipChat_Project
    source .venv/bin/activate
    python scripts/test_kicad_library.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import kicad_api, project_generator

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KICAD_LIB = os.path.join(PROJECT_DIR, os.pardir, "KICAD_Library")
CUSTOM_SYMBOLS = os.path.join(KICAD_LIB, "Symbols")
OFFICIAL_SYMBOLS = os.path.join(KICAD_LIB, "kicad-symbols")
OFFICIAL_FOOTPRINTS = os.path.join(KICAD_LIB, "kicad-footprints")
OFFICIAL_3D = os.path.join(KICAD_LIB, "kicad-packages3D")

OUTPUT_DIR = os.path.join(PROJECT_DIR, "generated", "library_test")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "library_test.kicad_sch")


def check_repos():
    """Verify all library repos exist (quick existence check, no full scan)."""
    print("=" * 60)
    print("  Library Verification")
    print("=" * 60)

    checks = [
        ("Custom symbols", CUSTOM_SYMBOLS, "Resistor.kicad_sym"),
        ("Official symbols", OFFICIAL_SYMBOLS, "Timer.kicad_symdir"),
        ("Official footprints", OFFICIAL_FOOTPRINTS, "Package_SO.pretty"),
        ("Official 3D models", OFFICIAL_3D, "Package_SO.3dshapes"),
    ]

    all_ok = True
    for label, path, sentinel in checks:
        if not os.path.isdir(path):
            print(f"  MISSING: {label} ({path})")
            all_ok = False
            continue

        sentinel_path = os.path.join(path, sentinel)
        if os.path.exists(sentinel_path):
            print(f"  OK: {label} — verified via {sentinel}")
        else:
            print(f"  WARN: {label} exists but sentinel {sentinel} not found")

    print()
    return all_ok


def find_symbol_file(symbol_name, library_dir_name):
    """Find a .kicad_sym file inside an official .kicad_symdir library.

    Returns the directory path (to use as library_path) and the symbol name,
    or (None, None) if not found.
    """
    symdir = os.path.join(OFFICIAL_SYMBOLS, f"{library_dir_name}.kicad_symdir")
    if not os.path.isdir(symdir):
        print(f"  Library dir not found: {symdir}")
        return None, None

    sym_file = os.path.join(symdir, f"{symbol_name}.kicad_sym")
    if not os.path.isfile(sym_file):
        print(f"  Symbol file not found: {sym_file}")
        return None, None

    return symdir, symbol_name


def check_footprint(footprint_lib, footprint_name):
    """Check if a footprint .kicad_mod file exists."""
    fp_dir = os.path.join(OFFICIAL_FOOTPRINTS, f"{footprint_lib}.pretty")
    fp_file = os.path.join(fp_dir, f"{footprint_name}.kicad_mod")
    return os.path.isfile(fp_file)


def check_3d_model(model_lib, model_name):
    """Check if a 3D model .step file exists."""
    model_dir = os.path.join(OFFICIAL_3D, f"{model_lib}.3dshapes")
    model_file = os.path.join(model_dir, f"{model_name}.step")
    return os.path.isfile(model_file)


def main():
    if not check_repos():
        print("Some libraries are missing. Clone them first.")
        sys.exit(1)

    # Symbols to test: (display_name, symbol_name, library_source, library_path_or_dir)
    test_symbols = [
        {
            "label": "NE555D (official Timer lib)",
            "symbol_name": "NE555D",
            "library_dir": "Timer",
            "source": "official",
            "footprint_lib": "Package_SO",
            "footprint_name": "SOIC-8_3.9x4.9mm_P1.27mm",
            "model_3d_lib": "Package_SO",
            "model_3d_name": "SOIC-8_3.9x4.9mm_P1.27mm",
            "pins": ["1", "2", "3", "4", "5", "6", "7", "8"],
        },
        {
            "label": "STM32F103C8Tx (official MCU_ST_STM32F1 lib)",
            "symbol_name": "STM32F103C8Tx",
            "library_dir": "MCU_ST_STM32F1",
            "source": "official",
            "footprint_lib": "Package_QFP",
            "footprint_name": "LQFP-48_7x7mm_P0.5mm",
            "model_3d_lib": "Package_QFP",
            "model_3d_name": "LQFP-48_7x7mm_P0.5mm",
            "pins": [str(i) for i in range(1, 49)],
        },
        {
            "label": "BME280 (custom lib)",
            "symbol_name": "BME280",
            "library_dir": None,
            "source": "custom",
            "footprint_lib": None,
            "footprint_name": None,
            "model_3d_lib": None,
            "model_3d_name": None,
            "pins": ["1", "2", "3", "4", "5", "6", "7", "8"],
        },
    ]

    # Create schematic
    import uuid as uuid_mod
    sheet_uuid = str(uuid_mod.uuid4())
    schematic = kicad_api.create_schematic_data("Library_Test", sheet_uuid)

    print("=" * 60)
    print("  Placing Test Symbols")
    print("=" * 60)

    x_pos = 100.0
    y_pos = 60.0
    y_spacing = 80.0
    success_count = 0

    for i, sym in enumerate(test_symbols):
        print(f"\n--- {sym['label']} ---")

        # Resolve library path
        if sym["source"] == "official":
            lib_path, sym_name = find_symbol_file(sym["symbol_name"], sym["library_dir"])
            if not lib_path:
                print(f"  SKIP: could not find symbol")
                continue
        else:
            lib_path = CUSTOM_SYMBOLS
            sym_name = sym["symbol_name"]

        # Embed symbol
        lib_id = kicad_api.embed_symbol_from_file(schematic, sym_name, library_path=lib_path)
        if not lib_id:
            print(f"  FAIL: could not embed symbol")
            continue

        # Place it
        pos_y = y_pos + i * y_spacing
        ref = f"U{i + 1}"
        kicad_api.place_component(
            schematic, lib_id, ref, sym_name,
            (x_pos, pos_y), angle=0,
            footprint="", pins=sym["pins"],
        )
        success_count += 1

        # Check footprint
        if sym["footprint_lib"] and sym["footprint_name"]:
            fp_ok = check_footprint(sym["footprint_lib"], sym["footprint_name"])
            print(f"  Footprint {sym['footprint_lib']}/{sym['footprint_name']}: {'OK' if fp_ok else 'MISSING'}")

        # Check 3D model
        if sym["model_3d_lib"] and sym["model_3d_name"]:
            m3d_ok = check_3d_model(sym["model_3d_lib"], sym["model_3d_name"])
            print(f"  3D model {sym['model_3d_lib']}/{sym['model_3d_name']}: {'OK' if m3d_ok else 'MISSING'}")

    # Save schematic
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    kicad_api.save_schematic(schematic, OUTPUT_FILE)

    # Generate .kicad_pro so KiCad can open the project directly
    PROJECT_NAME = "library_test"
    project_generator.generate_project_file(PROJECT_NAME, OUTPUT_DIR)
    pro_file = os.path.join(OUTPUT_DIR, f"{PROJECT_NAME}.kicad_pro")

    print("\n" + "=" * 60)
    print(f"  Results: {success_count}/{len(test_symbols)} symbols placed")
    print(f"  Schematic: {OUTPUT_FILE}")
    print(f"  Project:   {pro_file}")
    print(f"  Open the .kicad_pro in KiCad to verify symbols render correctly.")
    print("=" * 60)


if __name__ == "__main__":
    main()
