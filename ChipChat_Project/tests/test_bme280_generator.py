"""
Simple test: BME280 at center + R7 at top-left with net labels.
Baseline for getting placement, wires, and labels right.
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import schematic_generator

# Output path
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_FILE = os.path.join(PROJECT_DIR, "generated", "BME280_Test.kicad_sch")

if __name__ == "__main__":
    print("=" * 50)
    print("Simple Test: BME280 + R7")
    print("=" * 50)
    
    schematic_generator.generate_simple_test(OUTPUT_FILE)
    
    print(f"\nOpen in KiCad: {OUTPUT_FILE}")
