# SchematIQ Project Status

## Done
- **Component database**: Master `components.json` with BME280, USB-C, TPS628438DRL, MCP2221A specs
- **Project JSON**: `project_dummy.json` structure with sheets, components, passives, nets
- **Project builder**: Copies components from DB to project.json, auto-assigns refs
- **Schematic generator**: Generates BME280_Sensor sheet with components, wires, labels
- **Folder structure**: Organized into `src/lib/`, `data/`, `generated/`, `docs/`, `tests/`
- **Device symbols**: Fixed Device:R and Device:C embedding (proper KiCad format)
- **Project paths**: Fixed KiCad project file to reference `generated/` folder

## Next
- [ ] Test Device symbols display correctly in KiCad
- [ ] Improve wire routing (avoid crossovers, use full page)
- [ ] Generate remaining sheets (USBC, Buck_Converter, USB_To_I2C)
- [ ] LLM integration for net generation
- [ ] LLM integration for passive component addition

## Structure
```
Code/
├── src/lib/          # Core modules (kicad_api, project_builder, schematic_generator)
├── data/             # JSON files (project_dummy.json, project.json)
├── generated/         # Generated .kicad_sch files
├── docs/             # Documentation
└── tests/            # Test scripts
```
