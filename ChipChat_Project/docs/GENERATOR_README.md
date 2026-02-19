# BME280 Sensor Schematic Generator

This module generates a complete KiCad schematic sheet for the BME280_Sensor from `project.json`.

## How to Run

### Option 1: Using the test script (Recommended)

```bash
cd ChipChat_Project
python test_bme280_generator.py
```

This will:
- Read from `project_dummy.json` (or `project.json` if you modify the script)
- Generate `BME280_Test.kicad_sch` in the same directory

### Option 2: Using Python directly

```python
import schematic_generator

schematic_generator.generate_bme280_sensor_sheet(
    "project_dummy.json",  # or "project.json"
    "BME280_Test.kicad_sch"
)
```

## Testing in KiCad

1. **Open KiCad** (version 8.0 or later recommended)

2. **Open the generated file:**
   - File → Open → Navigate to `ChipChat_Project/BME280_Test.kicad_sch`
   - Or drag and drop the file into KiCad

3. **What to check:**
   - ✓ U3 (BME280) component is placed
   - ✓ R5, R6, R9 resistors are placed
   - ✓ C9, C10 capacitors are placed
   - ✓ Power symbols (+3.3V, GND) are visible
   - ✓ Hierarchical labels (I2C_SCL_BME, I2C_SDA_BME) on left side
   - ✓ Local labels (PP_3V3_OUT, I2C_SCL_OR, I2C_SDA_OR, SDO_ADD)
   - ✓ Wires connecting components according to nets

4. **If symbols don't load:**
   - Check that `KICAD_Library/Symbols/BME280.kicad_sym` exists
   - Device:R and Device:C are standard KiCad symbols (should work automatically)
   - Power symbols (power:+3.3V, power:GND) are standard KiCad symbols

## Output File

The generator creates `BME280_Test.kicad_sch` which is a standalone schematic file. It's separate from:
- `ChipChat_Project.kicad_sch` (main project file)
- `ChipChat_Project.kicad_pro` (project file)

You can open it independently in KiCad.

## What Gets Generated

1. **Components:**
   - U3: BME280 sensor (from symbol library)
   - R5, R6: 4.7K pull-up resistors
   - R9: 0R address select resistor
   - C9, C10: 0.1uF decoupling capacitors

2. **Power Symbols:**
   - +3.3V power rail (top)
   - GND symbols (bottom)

3. **Labels:**
   - Hierarchical: I2C_SCL_BME, I2C_SDA_BME (left side)
   - Local: PP_3V3_OUT, I2C_SCL_OR, I2C_SDA_OR, SDO_ADD

4. **Wires:**
   - Automatically generated based on net connections in `project.json`
   - Connects component pins to nets

## Layout Algorithm

The generator uses a simple algorithmic layout (Approach C: Hybrid):
- Components are placed at predefined positions
- Wires use a star topology (all pins on a net connect to a central point)
- Labels are placed at predefined positions

This is a basic implementation - more sophisticated routing algorithms can be added later.

## Troubleshooting

**Error: "Symbol file not found"**
- Check that `KICAD_Library/Symbols/BME280.kicad_sym` exists
- Update `DEFAULT_SYMBOL_PATH` in `kicad_api.py` if needed

**Components appear but no wires:**
- Check that `project.json` has the `nets` section with connections
- Verify that connections include `"sheet": "BME280_Sensor"` for this sheet

**KiCad shows errors when opening:**
- Make sure you're using KiCad 8.0 or later (version 20250114)
- Check the file encoding is UTF-8
- Look at KiCad's error messages for specific issues
