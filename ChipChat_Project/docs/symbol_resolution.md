# Symbol resolution & schematic generation

This doc summarizes how LLM JSON becomes KiCad symbols, optional improvements, and when an **LLM repair pass** is worth it.

## Current pipeline (deterministic)

1. **`config/symbol_aliases.json`** — First mapping layer. Add rows when the model invents wrong `lib:symbol` strings (e.g. `Diode:LED` → `Device:LED`) without editing Python.

2. **`symbol_aliases.normalize_symbol_lookup()`** — Built-in remaps (LED\_\*, `Connector_Generic:Connector_*` → `Conn_*`, FET → `Q_NMOS_GDS`, etc.). Kept in sync with `schematic_generator`.

3. **Packed library embed** — Exact `Lib:Name` in `KICAD_Library/kicad-symbols/*.kicad_sym`.

4. **`symbol_resolver.resolve_in_packed_library()`** — Same-file fallbacks (e.g. `NPN` → `Q_NPN_BCE` inside `Transistor_BJT`).

5. **Global fuzzy match** — Last resort; short symbols are filtered so `Diode:LED` does not become `Simulation_SPICE:D`. Prefix matching uses **8-character** prefixes (and a **stem before `_`**, e.g. `nRF5340_SoC` → `nRF5340`) so `Conn_02x05_*` does not collapse to `Conn_01x01_Pin`. If the JSON lists **N** connections, fuzzy matches are rejected when the symbol has **fewer than N** pins (stops 10-pin headers from becoming a 1-pin stub). Prefer **`config/symbol_aliases.json`** for invented names (e.g. `Connector_Generic:Conn_02x05_SWD_JTAG_ARM` → `Connector:Conn_ARM_JTAG_SWD_10`).

6. **Passives** — `PASSIVE_CONFIG` in `schematic_generator.py`:
   - `R`, `C`, `L`, `FB` → custom `KICAD_Library/Symbols/`
   - `D` → TVS symbol in custom library (not a generic rectifier)
   - **`Diode`** (and aliases `schottky`, `d_schottky`, …) → **`Device:D`** in official `Device.kicad_sym`
   - Generic diodes use **`"type": "Diode"`** in JSON passives; pin **1 = anode**, **2 = cathode** in LLM style is swapped internally to match KiCad **1=K, 2=A**.

7. **Preflight** — `scripts/validate_llm_symbols.py` and `generate_from_llm.py --validate` check **components** only (not every passive type yet).

8. **Pin wiring** — Main symbols use numeric keys in KiCad. The generator maps:
   - **B/C/E**, **A/K**, **G/D/S** by name where needed
   - **Op-amps:** if `pin_name` is **OUT**, **IN+**, **IN-**, **VDD/V+**, **VSS/V-**, nets attach by **KiCad pin names** (`~`, `+`, `-`, `V+`, `V-`…) so datasheet pin *numbers* can differ from KiCad (e.g. MCP6001 SOT-23 vs `MCP6001R` symbol).
   - If `pin_name` is missing, JSON **pin** numbers are still used (fragile for multi-package parts).

## “Back of mind” improvements (no LLM)

| Idea | Benefit |
|------|--------|
| **`symbols_index.json`** built from all `.kicad_sym` | Search / validation / future RAG |
| **Strict mode** | Fail if no exact + alias + in-lib generic (no fuzzy) |
| **Validate passives** | Extend preflight for unknown `type` |
| **Single `symbol_hints.yaml`** | Aliases + “LLM synonyms” in one place |

## Invented parts (`OpAmp_Single`, etc.)

`new_component` in the playground **only saves JSON** — it does **not** create a \
`.kicad_sym` file. Placeholders must be mapped to a real KiCad symbol (see \
`config/symbol_aliases.json`, e.g. `OpAmp_Single` → `Amplifier_Operational:LM741`) \
or the JSON should use **`Amplifier_Operational:LM741`** (or another real symbol) \
directly. Prefer **pin_name**-based connections so package pin numbers can differ.

A **second LLM “repair” pass** is optional: run validation, then ask a model to \
replace unknown `part` strings using a short list of allowed `Library:Symbol` \
names — same as discussed elsewhere; not required if prompts forbid invented names.

## Using a second LLM to link symbols & pins

**When it helps:** Rare parts, wrong library names, or pin naming that does not match our heuristics — especially if you already pay for an API and want fewer manual alias edits.

**Suggested contract (repair pass):**

- **Input:** (1) Component/passive list from JSON, (2) validation errors, (3) **small** curated catalog excerpt or allowed `lib:symbol` list (from index), (4) optional datasheet pin table.
- **Output:** **JSON Patch** or full replacement only for `part` / `connections[].pin` fields — not free-form prose.
- **Guardrails:** Run `validate_llm_symbols.py` + `generate_from_llm.py --validate` after repair; reject if still failing or if patch touches unrelated fields.

**Risks:** Hallucinated symbols, cost/latency, and new bugs. Prefer fixing the **first** LLM prompt + deterministic layers first; add repair only when validation failures are frequent.

**Cheaper alternative:** On validation failure, **re-prompt the same design LLM** with the error list and 5–10 lines of “use `Device:D`, `Diode` passive type, …” — no separate model.

## LLM symbol repair (implemented fallback)

When deterministic resolution is not enough (new names, odd connectors, or you do not want to hand-edit aliases), use the **Gemini repair pass**. It is **not** a replacement for aliases — every suggestion is **re-checked** against your local KiCad index and pin-count rules before the JSON is updated.

| Step | What |
|------|------|
| 1 | `find_unresolved_components` lists `ref`, `part`, `lookup`, `min_pin_count`, … |
| 2 | **Ranked candidates** are built from `symbol_resolver.list_lib_colon_symbols()` (token overlap with the failing part — no need to send the whole library). |
| 3 | Gemini returns JSON `{"replacements":[{"ref":"…","part":"Lib:Sym","note":"…"}]}`. |
| 4 | Each `part` is verified with `preview_resolve` (+ pin count). Rejected rows are reported. |

**CLI**

```bash
cd ChipChat_Project
# Preview
python scripts/repair_llm_symbols.py data/your_board.json --dry-run
# Fix JSON in place + optional alias file
python scripts/repair_llm_symbols.py data/your_board.json --write --save-aliases
```

**One-shot with generation** (requires `GEMINI_API_KEY` in `.env`):

```bash
python scripts/generate_from_llm.py --repair data/your_board.json
```

Requires: `google-genai`, `python-dotenv`, and **`GEMINI_API_KEY`**.

## Quick reference for diode OR-ing JSON

- Put rectifiers in **passives** with `"type": "Diode"` (or `"Schottky"` — normalized to `Diode`).
- Connections: **pin `1`** = anode side (e.g. `V1_IN`), **pin `2`** = cathode side (e.g. shared `VOUT_ORed`).
