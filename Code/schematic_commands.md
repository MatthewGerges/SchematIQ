# Schematic commands (brief)

From repo root: `cd ChipChat_Project` and activate `.venv` if you use it.

## LLM playground (chat → JSON → KiCad + tscircuit)

```bash
python scripts/prompt_playground.py
```

On `done` / `quit`: saves `data/llm_output_<Project>.json`, runs generators for **KiCad and tscircuit**.

## Generate from existing JSON

- **KiCad only** (default):  
  `python scripts/generate_from_llm.py data/llm_output_MyBoard.json`

- **tscircuit only**:  
  `python scripts/generate_from_llm.py --target tscircuit data/llm_output_MyBoard.json`

- **Both**:  
  `python scripts/generate_from_llm.py --target both data/llm_output_MyBoard.json`

Then: `cd generated/<ProjectName>/tscircuit && npm install && npm run dev`

## KiCad symbol validation / LLM repair

- Validate symbols resolve:  
  `python scripts/generate_from_llm.py --validate data/board.json`

- LLM repair unresolved KiCad `part` strings:  
  `python scripts/repair_llm_symbols.py data/board.json --write`

## tscircuit part matcher (LLM → MPN + footprint overrides)

Writes/merges `config/tscircuit_part_overrides.json` (used by `tscircuit_generator.py`).

```bash
python scripts/repair_llm_tscircuit_parts.py data/board.json
python scripts/repair_llm_tscircuit_parts.py data/board.json --dry-run
```

## 2-LLM electrical review (JSON sanity check)

```bash
python scripts/review_llm_json.py data/board.json
python scripts/review_llm_json.py data/board.json --fail-on warning
```

Report: `reports/<file_stem>_electrical_review.json`

**Shape:** `merged.findings` = **errors** then **warnings** only (severity order, sorted by code). All **info** rows are collapsed into compact `merged.info.items` (`c` / `m`). Read **`merged.human_summary`** first (`headline`, `must_fix`, `double_check`). Counts: `merged.finding_counts`.

**Severities:** **error** = likely broken or unsafe; **warning** = risk or needs human check; **info** = optional note only. `--fail-on` uses **gate_severity** (warnings+errors only) so **info never fails the gate**. Unused pins: **`NC_*`** or omit the pin from `connections`.

## tscircuit schematic “green wires”

tscircuit **auto-draws schematic traces** between ports on the same net (`schematic-trace-solver`). Our generator uses `connections={{…}}` to nets without `<trace>` elements, but the **viewer can still render green lines** — that is engine routing, not something we fully disable. Subcircuits set **`schTraceAutoLabelEnabled`** to nudge **net labels** on complex routes; a label-only schematic (KiCad-style) is **not** guaranteed today.

## Optional: review before generate

```bash
python scripts/generate_from_llm.py --review --target both data/board.json
```

## Where “the database” lives

- **KiCad symbols**: bundled/custom `.kicad_sym` under the project + `config/symbol_aliases.json`; resolution in `src/lib/symbol_resolver.py`.
- **LLM component hints**: `../component_database/components.json` (relative to `ChipChat_Project`).
- **tscircuit**: no local symbol index for arbitrary `<chip>` schematic graphics (chips render as boxes). Passives use tscircuit built-in primitives. **MPN / footprint**: `config/tscircuit_part_overrides.json` + heuristics in `src/lib/tscircuit_generator.py`.
