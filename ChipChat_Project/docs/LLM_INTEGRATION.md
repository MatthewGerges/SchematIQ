# LLM Integration — Generating project.json from Natural Language

## Goal
User describes a board → LLM produces a valid `project_dummy.json` → existing code renders KiCad schematics.

---

## Recommended Path: Start Simple, Layer Up

### Phase 1 — API Playground (start here)
No UI. Just a Python script that sends one prompt to the Gemini API and prints the JSON.

```
python llm_generate.py "USB-C powered BME280 sensor board with buck converter"
```

**Why start here:**
- Zero frontend overhead
- Fast iteration on prompt engineering
- Easy to diff LLM output vs. `project_dummy.json`
- Can test in < 5 minutes

**What to build:**
- `src/lib/llm_client.py` — thin wrapper around Gemini API (send prompt, get JSON back)
- `scripts/llm_generate.py` — CLI tool: description in → project.json out
- Prompt template with `components.json` context + output schema

**Prompt structure:**
```
SYSTEM: You are an electronics design assistant. Generate a project JSON file
for a KiCad schematic given the user's board description.

Here is the component database (available parts):
{components.json contents}

Here is the exact JSON schema you must follow:
{schema derived from project_dummy.json}

Rules:
- Every IC needs decoupling caps on its power pins
- I2C buses need pull-up resistors
- USB-C needs CC resistors (5.1K to GND)
- TVS diodes on data lines for ESD protection
- Every net must appear in both "connections" on components AND in "nets" list
- Passive pin 1 = right side, pin 2 = left side (our wiring convention)

USER: {board description}
```

**Validation:** Compare output against `project_dummy.json` structure — check all required fields exist, nets are consistent, pin numbers match component database.

---

### Phase 2 — Multi-Turn API (iterate on sections)
Still no UI. Script sends multiple API calls, one per sheet.

```
Step 1: "What components do I need for a USB-C powered BME280 board?"
        → LLM returns component list + sheet assignments

Step 2: "Generate the USBC sheet connections for J1 with these passives: ..."
        → LLM returns USBC section of JSON

Step 3: Repeat for Buck_Converter, USB_To_I2C, BME280_Sensor

Step 4: "Generate the nets summary connecting all sheets"
        → LLM returns top-level nets list

Step 5: Algorithmic validation + fix-up pass
```

**Why multi-turn:**
- Smaller context per call = fewer hallucinations
- Can validate each sheet before moving on
- Easier to retry a single sheet if wrong
- Cheaper (less wasted tokens on correct sections)

---

### Phase 3 — Chat Interface (later)
Simple web UI where the LLM asks questions interactively.

**Flow:**
```
LLM: What kind of board do you want to build?
You: USB-C powered environmental sensor

LLM: I'll use: USB-C connector, TPS628438 buck, MCP2221A USB-I2C, BME280.
     Want to change anything?
You: Looks good

LLM: Generating USBC page... [shows component list + passives]
     Does this look right?
You: Add an extra 10uF cap on VBUS

LLM: Done. Generating Buck Converter page...
[continues sheet by sheet]

LLM: All sheets complete. Generating KiCad project...
     → outputs .kicad_pro + .kicad_sch files
```

**Tech options for frontend:**
| Option | Effort | Notes |
|--------|--------|-------|
| Streamlit | Low | Python-native, quick prototype, easy to deploy |
| Gradio | Low | Similar to Streamlit, good for ML demos |
| Next.js + API | Medium | Better UX, more work, good for production |
| Terminal chat | Minimal | Just `input()` in a loop, good enough for Phase 2.5 |

---

## Key Design Decisions

### What the LLM generates vs. what's algorithmic

| Task | LLM | Algorithm |
|------|-----|-----------|
| Component selection | ✓ | |
| Sheet assignments | ✓ | |
| Pin-to-net connections | ✓ | |
| Passive selection + values | ✓ | |
| Net naming | ✓ | |
| Component placement (x,y) | | ✓ (grid layout) |
| Wire routing | | ✓ (pin parser + stubs) |
| Label placement | | ✓ (from pin angles) |
| KiCad file generation | | ✓ (existing code) |

The LLM only needs to produce the **logical** design (what connects to what). The **physical** layout is handled by our existing `schematic_generator.py`.

### JSON Schema as Contract
The `project_dummy.json` structure IS the schema. The LLM's output must match it exactly. We can:
1. Include the schema in the prompt
2. Validate the output programmatically
3. Ask the LLM to fix validation errors in a follow-up call

### Component Database as Context
Feed `components.json` (or a filtered subset) to the LLM so it knows:
- Available parts and their pin definitions
- Pin names, numbers, and electrical types
- Voltage levels and interfaces

---

## Immediate Next Steps

1. **Get a Gemini API key** and test a basic call
2. **Write `llm_client.py`** — `generate_project_json(description, components_db) → dict`
3. **Write a prompt template** that includes schema + rules + component DB
4. **Test with the BME280 board description** — compare output to `project_dummy.json`
5. **Add validation** — check nets consistency, pin numbers exist, required fields present
6. **Iterate on the prompt** until output is reliably correct

---

## Cost Estimate (Gemini 2.0 Flash)
- Component DB context: ~3K tokens
- Schema + rules: ~2K tokens  
- LLM output (full project JSON): ~4K tokens
- **~$0.01-0.03 per generation** at current pricing
- Multi-turn (4 sheets): ~$0.05-0.10 per full board
