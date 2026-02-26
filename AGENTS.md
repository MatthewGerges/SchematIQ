# AGENTS.md

## Cursor Cloud specific instructions

### Overview

ChipChat is a pure Python project that generates KiCad schematic files from JSON project definitions. It has **zero third-party dependencies** — only Python 3 standard library modules are used (`json`, `uuid`, `os`, `sys`, `re`, `math`, `copy`).

### Running the application

The primary working entry point is:

```bash
cd ChipChat_Project
python3 tests/test_bme280_generator.py
```

This reads `data/project_dummy.json` and generates a full hierarchical KiCad project (root schematic + 4 sub-sheets + `.kicad_pro`) in the `generated/` directory.

### Known issues

- `src/main.py` contains hardcoded macOS paths for the symbol library and uses a stale `project_generator.generate_root_schematic()` signature. It will fail at runtime. Use `tests/test_bme280_generator.py` instead.

### Linting / Testing

There is no formal linting or test framework configured. Use `python3 -m py_compile <file>` to syntax-check individual modules. All core modules are in `ChipChat_Project/src/lib/`.

### Key directories

- `ChipChat_Project/src/lib/` — Core Python modules (kicad_api, schematic_generator, project_builder, project_generator)
- `ChipChat_Project/data/` — JSON project definitions (`project_dummy.json`, `project.json`)
- `ChipChat_Project/generated/` — Output KiCad files (regenerated on each run)
- `KICAD_Library/` — Custom KiCad symbol (`.kicad_sym`) and footprint (`.kicad_mod`) files
- `component_database/` — Master component database (`components.json`)
