# ECE 499 / SchematIQ — source notes for drafting

**Purpose:** Consolidated evidence base for writing the submitted report. **Not** submitted as-is. Polish and cite formally in the final document. Repository paths use `Code/` as in the codebase; narrative name **SchematIQ**.

**GenAI / course policy:** Align the final report’s **Generative AI acknowledgement** with supervisor and ECE 499 outline. Keep **prompts, drafts, and revision history** as the course recommends.

---

## 1. Project framing (Jan 30 meeting)

- **Pitch deck** (SchematIQ, formerly ChipChat): [Google Slides](https://docs.google.com/presentation/d/1HR19BHNGPZVwpnxgG9mfLZNjJxHL5GYmYCGyJeD7G3g/edit?usp=sharing)
- **Shift in emphasis:** From “product demo” toward **research-grade evaluation**—define **how success is measured**, not only that the tool works sometimes.
- **Takeaways for the report:**
  1. **Rigorous benchmarks** — quantify validity (e.g., fraction of intended connections realized, ERC outcomes, round-trip verifier pass rate).
  2. **Literature-aligned metrics** — cite PCB-Bench-style work (see §6).
  3. **Architecture split** — **LLM = reasoning / decisions**; **Python helpers = execution / KiCad syntax / placement**.
  4. **Edge cases** — impossible asks, very large designs.
- **Multi-model comparison (partial):** Notes included a **BME280 “no MCU” architecture** prompt and long responses across models (e.g., GPT-5.2, Claude Opus 4.6, Gemini 3 Pro, DeepSeek V3). A **comparison table was left incomplete**. The report should summarize **qualitatively** and state **scope**: implementation standardized on **Gemini 2.5 Flash** (`prompt_playground.py`, `webui_server.py`).

---

## 2. Planned project timeline (six phases)

| Phase | Dates (planned) | Focus | Deliverables (planned) |
| ----- | ----------------- | ----- | ---------------------- |
| 1 | Jan 30 – Feb 6 | LLM evaluation | Comparison matrix + model choice |
| 2 | Feb 6 – Feb 20 | KiCad internals + core APIs | Deterministic placement API |
| 3 | Feb 20 – Mar 6 | Multi-LLM architecture | Modular multi-LLM pipeline |
| 4 | Mar 6 – Mar 20 | Validation & DRC | DRC-clean outputs |
| 5 | Mar 20 – Mar 30 | End-to-end pipeline | Prompt → JSON → KiCad demo |
| 6 | Mar 30 – Apr 6 | Evaluation & reporting | Final report + presentation |

### Planned vs actual (for one short report paragraph)

- **Phase 3:** Evolved into **single-model chat + deterministic backend + repair/review** rather than a fully separate multi-LLM production stage; architecture remains modular for future models.
- **Phase 4:** **ERC-centric goals** overlap **custom round-trip verification**, **symbol preflight**, and **electrical review LLM** rather than a single DRC campaign.
- **Phase 2:** Risk of overrun was noted (Feb 19); mass-spring / force-directed placement deferred to future work.

---

## 3. Meeting and design notes (chronological)

### Feb 17 — JSON representation (Approach A / B / C)

- **Approach A:** Per-component `connections`.
- **Approach B:** Top-level `nets`.
- **Approach C:** Both (hybrid).
- **Implementation:** Hybrid JSON — component `connections` plus `nets`; report should justify **trade-offs** and **drift risk** if the two views disagree.

### Feb 19 — QA philosophy and future ideas

- Treat checks like **software assertions** (pins connected vs intentionally NC).
- Avoid **redundant JSON** where it creates maintenance burden.
- **Mass-spring / force-directed placement** noted as a **future** layout idea.
- Phase 2 may run long (KiCad internals).

### Mar 27 — UI, architecture alternatives, testing direction

- **UI polish** ongoing.
- **Alternative architecture:** LLM emits **KiCad S-expressions directly** vs current **JSON → Python** — trade-offs for Discussion / Future work.
- **Test plan idea:** **Intentional mistakes** (wrong voltage, VIH/VIL) to see if **electrical review** catches them; align with reporting timeline. If not run systematically, state as **planned evaluation** in Results.

---

## 4. Progress narrative (high level — Methods / Results)

Use as a **timeline sketch**; verify dates against git if the report needs exact commits.

| Period | Notes |
| ------ | ----- |
| Dec 2025 – Feb 2026 | Component DB, `project_dummy`-style JSON, `schematic_generator`, hierarchical sheets, BME280-focused development (e.g. Feb 23: full schematic generation from JSON — check `git log`). |
| Mar 3–4 | Gemini API wired; early outputs **wrong schema** → drove **`prompt_playground`**, **strict schema**, **`components.json` injection**. |
| Mar 10+ | `generate_from_llm.py`; multi-sheet BME280-style runs with **real errors** (e.g., MCP2221A VDD/VUSB levels, buck VSET) → **LLM + review** iteration; **symbol resolver**; **KiCad 9 vs 10** library issues. |
| Mar 15–18 | LED + NFET session: **duplicate components** in saved JSON, **wrong symbol resolution** (C vs connector) → generator/resolver fixes; **tscircuit** explored in parallel (live preview, different failure modes). |
| Ongoing | Web UI, **round-trip verifier**, ingest fixes for **stale passives**, pin-name matching, shield/GND auto-connect. |

---

## 5. Literature and evaluation methodology (formal cites in final report)

Summaries below are **drafting aids** — replace with proper bibliography entries (venue, year, authors) in the submitted References.

| # | Work (short) | One-line use in report |
| --- | --- | --- |
| 1 | **PCB-Bench** | LLM limits on PCB tasks; supports **offloading spatial work** to code. |
| 2 | **CIRCUIT** | Topology reasoning; **unit-test**-style evaluation; high failure rates despite plausible text. |
| 3 | **PCBSchemaGen** | Constraints / knowledge graph; supports **component DB + verification**. |
| 4 | **EngDesign** | Simulation-based evaluation; supports **ERC / tool-backed checks**. |
| 5 | **PCBAgent** | Agent split; supports **LLM vs algorithm division**. |
| 6 | **AEM-PCB** | Aesthetic / layout metrics; supports **placement quality** discussion (**future work**). |

### Proposed metric rows (mark status in the report)

| Metric / theme | Typical signal | SchematIQ status (for drafting) |
| -------------- | -------------- | -------------------------------- |
| Pin-role / connectivity intent | JSON vs schematic graph | **Implemented** — round-trip verifier (`schematic_verifier.py`) |
| JSON / IR validity | Parse + schema | **Implemented** |
| Symbol existence | Resolve + embed | **Implemented** — resolver + **symbol_preflight** + **symbol_repair_llm** |
| ERC | KiCad electrical rules | **Partial / goal** — frame honestly; emphasize verifier + preflight + review stack |
| Crossover / aesthetic placement | Layout metrics | **Future** — AEM-inspired; current grid + optional LLM placement |
| DRC | PCB rules | **Future** — schematic-first scope |

---

## 6. LLM benchmark / multi-model summary (qualitative)

**Prompt theme (notes):** BME280-centric design **without MCU** — exercises power narrative, I²C, sensor choice, connector strategy.

**Models discussed in planning (not all fully benchmarked in a single table):** e.g. GPT-5.2, Claude Opus 4.6, Gemini 3 Pro, DeepSeek V3.

**Outcome for the report:**

- State that a **full quantitative matrix** was **not completed**.
- **Qualitative** comparison may note: bridge vs level-shifter choices, power path coherence, verbosity, adherence to structured output when prompted.
- **Implementation choice:** **Gemini 2.5 Flash** for the main pipeline (cost, latency, API integration); **strong schema + component DB** as the primary control lever vs swapping models.

---

## 7. Systematic test prompts and generated projects (SET 1 / SET 2)

Use a **summary table** in Results: prompt theme → subsystem stressed → outcome (pass / fail / iterations) → path or screenshot.

Paths below are under `Code/generated/` (relative to repo root: `SchematIQ/Code/generated/`). Update outcomes from `Code/reports/*_verify_*.json` and `*_roundtrip_*.json` when writing numbers.

### SET 1 — basic blocks and power skeletons

| Prompt theme | What it stresses | Example `.kicad_pro` folder (repo) |
| ------------ | ---------------- | ----------------------------------- |
| Button + LED | Simple digital + LED | `Button_LED_Board/` |
| RC low-pass | Passive AC | `RC_Low_Pass_Filter_Test_Board/` (also `RC_Low_Pass_Filter_Board/`) |
| Voltage divider + ADC header | Analog front + connector | `Voltage_Divider_Test_Board/` |
| NPN low-side LED | BJT switch / LED drive | `LED_Driver_Board/`, `Signal_Generator_LED_Test_Board/` |
| Diode OR-ing | Power path / diodes | `Power_ORing/` |
| Simple buck skeleton | Switching regulator structure | `Simple_Buck_Converter_Test_Board/` |

### SET 2 — mismatch lessons, analog, complex MCU sheet

| Prompt theme | What it stresses | Example `.kicad_pro` folder (repo) |
| ------------ | ---------------- | ----------------------------------- |
| Voltage divider + buffer | JSON vs schematic **pin_name** / pin matching | `Voltage_Buffer_Board/` |
| Non-inverting op-amp | Analog feedback | `Main_Amplifier_Circuit/` |
| Nordic nRF5340 power + SWD | Connectors, **LLM symbol repair**, multi-block | `nRF5340_BaseBoard/` |

### Additional stress tests (verifier / regulator / sensor narratives)

| Theme | Example folder |
| ----- | -------------- |
| LDO / regulator variants | `LDO_Breakout_Board/`, `LDO_Breakout_5V_to_3V3/`, `LDO_Breakout_5V_to_3V3_500mA/`, `5V_to_3V3_LDO_Breakout/` |
| Buck | `Buck_Converter_Breakout/`, `Buck_Boost_Efficiency_Board/` |
| BME280 / USB | `USB_C_BME280_Sensor_Board/`, `BME280_Tester_NoMCU/` |
| MAX30102 multi-sheet | `MAX30102_Breakout/`, `MAX30102_LMT86_Breakout/` |
| Symbol embed / hierarchy | `Symbol_Embed_Test/` |
| Simple LED baseline | `LED_Blink_Project/` |

**Report artifacts:** `Code/reports/` — e.g. `*_placement.json`, `*_verify_*.json`, `*_roundtrip_*.json`, `llm_output_electrical_review.json`.

---

## 8. Verification / bugs narrative (examples for §8.4)

**KiCad schematic ERC (first manual opens):** Summarized in the submitted report as **§7.3.1**—power-not-driven (**PWR_FLAG**), library-table vs embedded **`lib_id`**, and pin-level connectivity overlapping §7.4 / verifier.

Short list for “bugs found and fixed” storytelling:

- LM1117LD-3.3: **VO vs VOUT** pin naming; **2-char substring** threshold in matching.
- BME280: **duplicate GND** pin — **Priority 1** pin-number match behavior.
- USB: **shield** pin auto-connect to ground.
- Sheet redesign: **stale passives** after replacing a topology (ingest clears sheet state).
- LED/NFET run: **duplicate refs**, **wrong symbol class** (connector vs capacitor) — **generator / resolver** fixes.

---

## 9. Alternate tooling (Discussion / Future work)

- **tscircuit:** Explored for TSX-centric schematic and **live preview**.
- **Pros:** Fast feedback, web-native editing metaphor.
- **Cons vs KiCad-first:** Different failure modes, maturity vs fabrication-oriented **KiCad** output.
- **Report line:** Secondary path; primary evaluation target remains **KiCad** + verifier.

---

## 10. Key code and data paths (appendix pointers)

| Item | Path |
| ---- | ---- |
| Master parts DB | `component_database/components.json` |
| Core libraries | `Code/src/lib/` (`kicad_api.py`, `project_generator.py`, `schematic_generator.py`, `symbol_resolver.py`, `schematic_verifier.py`, `symbol_repair_llm.py`, `schematic_placement_llm.py`, `electrical_review_llm.py`, `symbol_preflight.py`) |
| Prompts / playground | `Code/scripts/prompt_playground.py` |
| Batch generation + verify | `Code/scripts/generate_from_llm.py` |
| Web backend | `Code/scripts/webui_server.py` |
| Symbol aliases | `Code/config/symbol_aliases.json` |
| LLM output JSON | `Code/data/llm_output*.json` |
| Web UI | `Code/webui/` |

---

## 11. Future work bullets (from plan — condense in report §9)

- **Recursive LLM repair:** Feed **round-trip diff** back into the model (Mar 27 direction).
- **Stronger tool-backed metrics:** Systematic **KiCad ERC**; expand benchmark toward literature table.
- **Placement:** Mass-spring / force-directed or constraint-based layout; AEM-inspired scoring.
- **Alternative IR:** LLM emits **KiCad S-expressions** directly vs **JSON IR** — trade-offs.
- **One-liners if space tight:** Footprint assignment and PCB layout; expanded DB; multi-user; deeper **tscircuit** integration.

---

*Last updated: consolidated for report drafting from project plan and repo layout (April 2026).*
