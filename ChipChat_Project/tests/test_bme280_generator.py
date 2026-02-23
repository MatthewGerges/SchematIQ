"""
Generate full hierarchical KiCad project from project_dummy.json.

Creates:
  1. Root schematic  (BME280_Rev1.kicad_sch)  — sheet boxes + hier pins
  2. Project file    (BME280_Rev1.kicad_pro)
  3. Sub-sheets      (USBC.kicad_sch, Buck_Converter.kicad_sch, etc.)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import schematic_generator, project_generator

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(PROJECT_DIR, "data", "project_dummy.json")
GEN_DIR = os.path.join(PROJECT_DIR, "generated")

if __name__ == "__main__":
    os.makedirs(GEN_DIR, exist_ok=True)

    # Read JSON for project name + sheet list
    with open(JSON_PATH) as f:
        data = json.load(f)

    project_name = data.get("project_name", "ChipChat_Project")
    sheets = data["sheets"]

    print("=" * 60)
    print(f"  Generating full project: {project_name}")
    print(f"  JSON:   {JSON_PATH}")
    print(f"  Output: {GEN_DIR}")
    print("=" * 60)

    # 1. Root schematic with hierarchical sheet boxes + pins
    print("\n--- Step 1: Root schematic ---")
    root_path, root_uuid, sheet_uuids = project_generator.generate_root_schematic(
        JSON_PATH, GEN_DIR, project_name
    )

    # 2. .kicad_pro
    print("\n--- Step 2: Project file ---")
    project_generator.generate_project_file(
        project_name, GEN_DIR, sheet_uuids=sheet_uuids
    )

    # 3. Each sub-sheet
    for sheet_def in sheets:
        sheet_name = sheet_def["name"]
        sheet_file = sheet_def["file"]
        output_path = os.path.join(GEN_DIR, sheet_file)

        print(f"\n--- Step 3: {sheet_name} → {sheet_file} ---")
        schematic_generator.generate_from_json(
            output_path, JSON_PATH, sheet_name=sheet_name
        )

    print("\n" + "=" * 60)
    print("  Done! Open in KiCad:")
    print(f"  {os.path.join(GEN_DIR, f'{project_name}.kicad_pro')}")
    print("=" * 60)
