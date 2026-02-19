"""
Test script to generate BME280_Sensor schematic sheet.
Run this to test the schematic generator.
"""

import os
import schematic_generator

# Paths
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_JSON = os.path.join(PROJECT_DIR, "project_dummy.json")  # Using dummy for now
OUTPUT_FILE = os.path.join(PROJECT_DIR, "BME280_Test.kicad_sch")

if __name__ == "__main__":
    print("=" * 60)
    print("BME280 Sensor Schematic Generator Test")
    print("=" * 60)
    print(f"\nInput:  {PROJECT_JSON}")
    print(f"Output: {OUTPUT_FILE}\n")
    
    # Generate the schematic
    schematic_generator.generate_bme280_sensor_sheet(
        PROJECT_JSON,
        OUTPUT_FILE
    )
    
    print("\n" + "=" * 60)
    print("Generation complete!")
    print("=" * 60)
    print(f"\nTo test in KiCad:")
    print(f"  1. Open KiCad")
    print(f"  2. File -> Open -> {OUTPUT_FILE}")
    print(f"  3. Check if components, wires, and labels appear correctly")
    print(f"\nNote: You may need to adjust symbol library paths if symbols don't load.")
