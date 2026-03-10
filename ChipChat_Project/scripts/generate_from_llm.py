"""
Generate KiCad project from llm_output.json (produced by prompt_playground.py).

Same pipeline as tests/test_bme280_generator.py but reads from llm_output.json
and outputs to generated/llm_<project_name>/ to keep it separate.

Usage:
    cd ChipChat_Project
    source .venv/bin/activate
    python scripts/generate_from_llm.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import schematic_generator, project_generator

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(PROJECT_DIR, "data", "llm_output.json")
GEN_DIR = os.path.join(PROJECT_DIR, "generated")

if __name__ == "__main__":
    if not os.path.exists(JSON_PATH):
        print(f"ERROR: {JSON_PATH} not found. Run prompt_playground.py first.")
        sys.exit(1)

    with open(JSON_PATH) as f:
        data = json.load(f)

    project_name = data.get("project_name", "LLM_Project")
    sheets = data["sheets"]

    output_dir = os.path.join(GEN_DIR, project_name)
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print(f"  Generating KiCad project from LLM output")
    print(f"  Project: {project_name}")
    print(f"  JSON:    {JSON_PATH}")
    print(f"  Output:  {output_dir}")
    print(f"  Sheets:  {[s['name'] for s in sheets]}")
    print("=" * 60)

    # 1. Root schematic with sheet boxes
    print("\n--- Step 1: Root schematic ---")
    root_path, root_uuid, sheet_uuids = project_generator.generate_root_schematic(
        JSON_PATH, output_dir, project_name
    )

    # 2. .kicad_pro
    print("\n--- Step 2: Project file ---")
    project_generator.generate_project_file(
        project_name, output_dir, sheet_uuids=sheet_uuids
    )

    # 3. Each sub-sheet
    errors = []
    for sheet_def in sheets:
        sheet_name = sheet_def["name"]
        sheet_file = sheet_def["file"]
        output_path = os.path.join(output_dir, sheet_file)

        print(f"\n--- Step 3: {sheet_name} → {sheet_file} ---")
        try:
            schematic_generator.generate_from_json(
                output_path, JSON_PATH, sheet_name=sheet_name
            )
        except Exception as e:
            errors.append((sheet_name, str(e)))
            print(f"  ERROR on {sheet_name}: {e}")

    print("\n" + "=" * 60)
    if errors:
        print(f"  Completed with {len(errors)} error(s):")
        for name, err in errors:
            print(f"    {name}: {err}")
    else:
        print("  Done! Open in KiCad:")
    print(f"  {os.path.join(output_dir, f'{project_name}.kicad_pro')}")
    print("=" * 60)
