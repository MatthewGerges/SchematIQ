# ChipChat Architecture

## Flow

```
component_database/components.json   (master specs — pins, voltages, VIH/VIL)
        │
        ▼  project_helper.create_project()
ChipChat_Project/project.json        (project copy of specs, later: connections)
        │
        ▼  kicad_api functions
ChipChat_Project/*.kicad_sch          (actual KiCad schematic files)
```

## Structure

```
ChipChat_Gemini/
├── component_database/
│   └── components.json       # Master component library
├── KICAD_Library/Symbols/    # .kicad_sym files
├── ChipChat_Project/
│   ├── project.json          # Components for this project (copied from master DB)
│   ├── project_helper.py     # Copy parts from master DB → project JSON
│   ├── kicad_api.py          # Generate .kicad_sch files
│   ├── main.py               # Entry point
│   └── *.kicad_sch           # Generated schematic sheets
└── BME280_Rev1/              # Reference project
```

## Status

- [x] Master database with 4 components (BME280, USB-C, TPS628438, MCP2221A)
- [x] Helper function to copy parts into project JSON
- [ ] Net connections between components
- [ ] Passive components (resistors, capacitors)
- [ ] Generate schematic sheets from project JSON
