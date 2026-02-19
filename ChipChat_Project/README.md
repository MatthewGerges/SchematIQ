# ChipChat Project

AI-powered PCB schematic generation using LLMs and algorithmic layout.

## Quick Start

```bash
# Generate BME280 sensor schematic
cd ChipChat_Project
python tests/test_bme280_generator.py
```

Output: `generated/BME280_Test.kicad_sch`

## Structure

- `src/lib/` - Core modules (kicad_api, project_builder, schematic_generator)
- `data/` - JSON files (project_dummy.json, project.json)
- `generated/` - Generated .kicad_sch files
- `docs/` - Documentation
- `tests/` - Test scripts

## Status

See `docs/PROJECT_STATUS.md` for current progress and next steps.
