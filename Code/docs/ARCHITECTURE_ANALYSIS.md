# Component Database Architecture Analysis

## Tradeoffs: Pre-created JSON Database vs. On-the-spot Creation

### Option 1: Pre-created Master Database (RECOMMENDED)

**Pros:**
- ✅ **Reusability**: One source of truth for component specs across all projects
- ✅ **Consistency**: Same component always has same data structure
- ✅ **Maintainability**: Update once, use everywhere
- ✅ **Speed**: No need to look up datasheets/parse symbols each time
- ✅ **Version Control**: Can track changes to component specs over time
- ✅ **LLM-Friendly**: Can be queried by LLMs for design decisions
- ✅ **Validation**: Can validate connections against electrical specs (VIH/VIL, voltage levels)
- ✅ **Future-Proof**: Foundation for automated design rule checking

**Cons:**
- ⚠️ **Initial Setup**: Time investment to create initial database
- ⚠️ **Maintenance**: Need to keep database updated when components change
- ⚠️ **Storage**: Larger files (but negligible for modern systems)

### Option 2: On-the-spot Creation

**Pros:**
- ✅ **No Upfront Work**: Generate as needed

**Cons:**
- ❌ **Inconsistency**: Same component might have different structures
- ❌ **Redundancy**: Recreating same data multiple times
- ❌ **Error-Prone**: Manual entry each time
- ❌ **No Validation**: Can't check electrical compatibility
- ❌ **Slower**: Need to parse symbols/look up datasheets repeatedly

## Recommended Architecture

### Structure:

```
SchematIQ/
├── component_database/          # Master component library
│   ├── components.json           # All component specs
│   └── README.md                 # Database schema documentation
│
├── Code/             # Application / Python project
│   ├── project.json              # Project-specific data
│   └── ...
│
└── BME280_Rev1/                  # Another project
    ├── project.json              # Project-specific data
    └── ...
```

### Master Database Schema (`component_database/components.json`):

```json
{
  "BME280": {
    "name": "BME280",
    "manufacturer": "Bosch",
    "part_number": "BME280",
    "type": "sensor",
    "description": "3-in-1 sensor, humidity, pressure, temperature",
    "interfaces": ["I2C", "SPI"],
    "voltage_range": {
      "min": 1.71,
      "max": 3.6,
      "unit": "V"
    },
    "symbol": {
      "library": "KICAD_Library/Symbols/BME280.kicad_sym",
      "lib_id": "BME280"
    },
    "footprint": {
      "library": "Footprint_Library",
      "name": "BME280"
    },
    "pins": [
      {
        "number": "1",
        "name": "GND",
        "type": "power_in",
        "function": "ground",
        "voltage": {
          "min": 0,
          "max": 0,
          "unit": "V"
        }
      },
      {
        "number": "2",
        "name": "CSB",
        "type": "input",
        "function": "chip_select_bar",
        "voltage": {
          "vih_min": 0.7,
          "vil_max": 0.3,
          "unit": "V"
        }
      },
      {
        "number": "6",
        "name": "VDDIO",
        "type": "power_in",
        "function": "io_power",
        "voltage": {
          "min": 1.71,
          "max": 3.6,
          "unit": "V"
        }
      },
      {
        "number": "8",
        "name": "VDD",
        "type": "power_in",
        "function": "core_power",
        "voltage": {
          "min": 1.71,
          "max": 3.6,
          "unit": "V"
        }
      }
    ],
    "datasheet": "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf"
  }
}
```

### Project JSON Schema (`Code/project.json`):

```json
{
  "project_name": "Example_Project",
  "version": "1.0",
  "components": [
    {
      "instance_id": "U1",
      "part": "BME280",  // Reference to master database
      "sheet": "BME280_Sensor.kicad_sch",
      "position": {
        "x": 148.5,
        "y": 105.0
      },
      "connections": [
        {
          "pin": "6",
          "net": "VDDIO_3V3",
          "hierarchical_label": "VDDIO_3V3"
        },
        {
          "pin": "8",
          "net": "VDD_3V3",
          "hierarchical_label": "VDD_3V3"
        },
        {
          "pin": "1",
          "net": "GND",
          "hierarchical_label": "GND"
        },
        {
          "pin": "3",
          "net": "I2C_SDA",
          "hierarchical_label": "I2C_SDA_BME"
        },
        {
          "pin": "4",
          "net": "I2C_SCL",
          "hierarchical_label": "I2C_SCL_BME"
        }
      ]
    },
    {
      "instance_id": "U2",
      "part": "MCP2210-I_SO",
      "sheet": "MCP2210_USB_TO_SPI.kicad_sch",
      "position": {
        "x": 100.0,
        "y": 100.0
      },
      "connections": [
        {
          "pin": "1",
          "net": "VDD_5V",
          "hierarchical_label": "VDD_5V"
        },
        {
          "pin": "20",
          "net": "GND",
          "hierarchical_label": "GND"
        },
        {
          "pin": "9",
          "net": "SPI_MOSI",
          "hierarchical_label": "SPI_MOSI"
        }
      ]
    }
  ],
  "nets": [
    {
      "name": "VDDIO_3V3",
      "voltage": {
        "min": 3.0,
        "max": 3.6,
        "unit": "V"
      },
      "connections": [
        {"component": "U1", "pin": "6"}
      ]
    },
    {
      "name": "I2C_SDA",
      "connections": [
        {"component": "U1", "pin": "3"},
        {"component": "U2", "pin": "13"}
      ]
    }
  ],
  "passives": [
    {
      "type": "resistor",
      "reference": "R1",
      "value": "4.7K",
      "purpose": "I2C_pullup",
      "connections": [
        {"net": "I2C_SDA", "side": "top"},
        {"net": "VDDIO_3V3", "side": "bottom"}
      ]
    }
  ]
}
```

## Implementation Strategy

### Phase 1: Master Database
1. Create `component_database/components.json` with BME280 and MCP2210
2. Create helper functions to:
   - Load component from master database
   - Validate component data structure
   - Query components by name/type

### Phase 2: Project JSON System
1. Create `project.json` template
2. Create functions to:
   - Copy component from master DB to project JSON
   - Add connections to project JSON
   - Generate schematic from project JSON

### Phase 3: Connection System
1. Parse project JSON connections
2. Generate wires, net labels, hierarchical labels
3. Add passive components based on connections

## Benefits of This Approach

1. **Separation of Concerns**: 
   - Master DB = "What is this component?"
   - Project JSON = "How is it used in this project?"

2. **Scalability**: 
   - Add new components to master DB once
   - Reuse across all projects

3. **Validation**: 
   - Can check if VDDIO (3.3V) connects to VDD (5V) → ERROR!
   - Can verify VIH/VIL compatibility

4. **LLM Integration**: 
   - LLM can query master DB for component specs
   - LLM can suggest connections based on electrical specs

5. **Version Control**: 
   - Master DB changes tracked separately
   - Project JSONs are smaller and focused

## Next Steps

1. Create master database structure with BME280 and MCP2210
2. Create project JSON structure for Code
3. Build helper functions to load/copy components
4. Extend API to generate connections from project JSON
