"""
Generate BME280_Sensor schematic from project_dummy.json.
All passives placed algorithmically (horizontal, column grid).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import schematic_generator

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(PROJECT_DIR, "data", "project_dummy.json")
OUTPUT_FILE = os.path.join(PROJECT_DIR, "generated", "BME280_Test.kicad_sch")

if __name__ == "__main__":
    print("=" * 50)
    print("BME280 Page — from project_dummy.json")
    print("=" * 50)
    print(f"  JSON:   {JSON_PATH}")
    print(f"  Output: {OUTPUT_FILE}\n")

    schematic_generator.generate_from_json(
        OUTPUT_FILE, JSON_PATH, sheet_name="BME280_Sensor"
    )

    print(f"\nOpen in KiCad: {OUTPUT_FILE}")
