"""
Interactive LLM Design Playground: multi-turn chat with Gemini for PCB design.

The LLM acts as an electronics design assistant — uses its own EE knowledge,
asks about your requirements, and builds up a project JSON sheet by sheet.

Usage:
    cd ChipChat_Project
    source .venv/bin/activate
    python scripts/prompt_playground.py

Commands during chat:
    quit / done  — save project JSON and exit
    save         — save current progress without exiting
    status       — show what's been accumulated so far
"""

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv  # pip install python-dotenv
try:
    from google import genai  # pip install google-genai
except ImportError as e:
    print("ImportError: google-genai is required. From ChipChat_Project directory:")
    print("  source .venv/bin/activate")
    print("  pip install google-genai python-dotenv")
    sys.exit(1)
from google.genai import types
from google.genai.types import GoogleSearch, Tool

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

COMP_DB_PATH = ROOT.parent / "component_database" / "components.json"
# Default filenames live under ROOT/data but we now generate unique names per
# project (e.g. llm_output_LED_Blink_Project.json) instead of always
# overwriting llm_output.json.
OUTPUT_DIR = ROOT / "data"
NEW_COMP_PATH = OUTPUT_DIR / "llm_components.json"

# ── Model (see test_gemini_api.py for full list of options) ──────────────────
MODEL = "gemini-2.5-flash"

# ── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an electronics design assistant helping a user create a KiCad schematic project.
You think like a real EE — you consult datasheets, check typical application \
circuits, and verify every pin connection before committing a design.

## Your Workflow

1. Greet the user.
2. Ask: "Would you like me to walk you through each design decision, or should \
I make the decisions myself and present my reasoning for you to approve?"
3. Based on their answer, gather requirements:
   - What is the board for? What does it need to do?
   - Key constraints: cost, size, power, interfaces?
   - Any specific ICs or parts they want to use?
4. Identify the core ICs needed. Each core IC (or major functional block like \
a connector) gets its own schematic sheet. Propose the sheet structure to the user.
   - Core components = ICs, connectors, major functional blocks → go in "sheets" \
and "components"
   - Sub-components = resistors, capacitors, inductors, diodes, ferrite beads → \
go in "passives"
5. Once the user approves the sheet structure, go sheet by sheet. For each sheet \
you MUST follow the Per-IC Design Checklist below BEFORE outputting any JSON.
6. After all sheets are done, generate:
   - The cross-sheet (hierarchical) nets that connect signals between sheets
   - The GND power net with all ground connections across all sheets
   - Output these as a final JSON code block
7. Ask the user if they'd like to review or modify anything, then tell them to \
type "done" to save.

## Per-IC Design Checklist (MANDATORY for every sheet)

Before outputting any sheet JSON, you MUST work through these steps for each \
core IC on that sheet. Present your reasoning to the user.

**Step A — Summarize the IC:** What does this IC do? What are its key features \
and operating conditions?

**Step B — Review EVERY pin:** Go through each pin on the IC. State its function \
and what it should connect to in this specific application. Pay special attention \
to power pins — verify voltage levels match the design.

**Step C — Check configurable pins:** For any pin that sets a mode, voltage, \
address, or other parameter (VSET, SDO, EN, CSB, etc.):
   - Look up the configuration table in the component database "design_notes"
   - If not in our database, use Google Search to find the datasheet
   - State the exact resistor value, connection, or setting needed and WHY

**Step D — Reference typical application:** Check the "design_notes" \
typical_application field. If not available, search the datasheet for the \
reference/typical application circuit. Compare your design against it.

**Step E — List all required passives:** For each passive, state:
   - What it is and its value (with justification from datasheet)
   - Which pins it connects between
   - Why it's needed

**Step F — Present and confirm:** Show your complete design to the user. \
Only output the JSON code block after presenting your reasoning.

## Component Database

Here are the parts currently in our KiCad library with exact pin definitions \
AND design notes extracted from datasheets. The "design_notes" field contains \
critical information — READ IT CAREFULLY for every component you use.

When you use one of these parts, you MUST:
- Use the exact pin numbers and pin names listed
- Follow the guidance in "design_notes" (especially "critical_notes")
- Use the recommended passive values from "design_notes"

If you need a part NOT in this database, you may still use it **only if** you can \
reference a **real KiCad symbol** that already exists in the official libraries. \
Look up the symbol in KiCad (or ask to use a common one): e.g. \
**Amplifier_Operational:LM741** (classic 8-pin single op-amp), \
**Amplifier_Operational:MCP6001R** (SOT-23-5), **Device:R**, **Device:LED**, \
**Connector_Generic:Conn_01x02**, **Connector:Conn_ARM_JTAG_SWD_10** (10-pin 1.27 mm Cortex SWD). \
Put that string in JSON as **"part": "Library:SymbolName"**. Do **not** invent symbols like \
`Connector_Generic:Conn_02x05_SWD_JTAG_ARM` — use a real name from KiCad or a generic \
**Connector_Generic:Conn_02x05_Odd_Even** / **Conn_01x06** if you must approximate pin count.

**Do NOT** invent placeholder part names like `OpAmp_Single` or `GENERIC_OPAMP` — \
they are not KiCad symbols and the schematic will not place. **Do NOT** use \
```new_component``` for generic placeholders; that block is only for **real** new \
MPNs we will later add to the library with a generated symbol file.

We resolve symbols by name in the KiCad library (custom + official): exact match, \
then prefix match, then first-6-characters match. Use the exact KiCad symbol name \
when you know it (e.g. LM1117DT-3.3, nRF5340-QKxx); for generic headers use \
**Connector_Generic:Conn_01x02** / **Conn_01x03** (prefix **Conn_**, not **Connector_**). \
Use Google Search for datasheets and the Per-IC Design Checklist.

{components_db}

## JSON Output Format

When you're ready to commit a design section, output it as a fenced JSON code block.

### Sheet list (after step 4, once user approves core ICs):
```json
{{
  "project_name": "ProjectName",
  "description": "Brief description of the board",
  "sheets": [
    {{"name": "SheetName", "file": "SheetName.kicad_sch", "page": 2}}
  ]
}}
```

### Per-sheet design (step 5, one block per sheet):
```json
{{
  "sheet_design": "SheetName",
  "components": [
    {{
      "ref": "J1",
      "part": "PartName_from_database_or_new",
      "sheet": "SheetName",
      "note": "human-readable note about what passives this needs",
      "connections": [
        {{"pin": "A4", "pin_name": "VBUS+", "net": "YOUR_NET_NAME"}}
      ]
    }}
  ],
  "passives": [
    {{
      "ref": "R1",
      "type": "R",
      "value": "5.1K",
      "sheet": "SheetName",
      "purpose": "CC1 pull-down for USB-C sink detection",
      "connections": [
        {{"pin": "1", "net": "SIGNAL_NET"}},
        {{"pin": "2", "net": "GND"}}
      ]
    }}
  ],
  "nets": [
    {{
      "name": "NET_NAME",
      "type": "local",
      "sheet": "SheetName",
      "connections": [
        {{"ref": "J1", "pin": "A4", "pin_name": "VBUS+"}},
        {{"ref": "C1", "pin": "1"}}
      ]
    }}
  ]
}}
```

### Cross-sheet nets (step 6):
```json
{{
  "cross_sheet_nets": [
    {{
      "name": "NET_NAME",
      "type": "hierarchical",
      "connections": [
        {{"ref": "J1", "pin": "A4", "pin_name": "VBUS+", "sheet": "USBC"}},
        {{"ref": "U1", "pin": "2", "pin_name": "VIN", "sheet": "Buck_Converter"}}
      ]
    }}
  ]
}}
```

### New component definition (for parts not in our database):
```new_component
{{
  "name": "PartName",
  "manufacturer": "Mfr",
  "part_number": "MPN",
  "type": "sensor | regulator | bridge | connector | etc",
  "description": "what it is",
  "interfaces": ["I2C", "SPI", "USB2.0"],
  "voltage_range": {{"min": 1.8, "max": 5.5, "unit": "V"}},
  "pins": [
    {{"number": "1", "name": "GND", "type": "power_in", "function": "ground"}}
  ]
}}
```

## Important Rules
- Passive pin 1 = signal side, pin 2 = power/ground side
- Allowed passive **type** strings: **R**, **C**, **L**, **FB**, **Diode** \
(generic rectifier / Schottky OR-ing → KiCad `Device:D`; pin **1 = anode**, \
**2 = cathode**), and **D** (TVS only — special symbol). Use **Diode** for \
normal diodes, not **D**.
- Reference designators: J=connector, U=IC, R=resistor, C=capacitor, \
L=inductor, D=diode, FB=ferrite bead
- Number passives sequentially across ALL sheets (R1, R2... C1, C2... not \
restarting per sheet)
- Use your own electronics knowledge for design decisions — do not ask the user \
for technical details you should know as an EE
- If the user wants a walkthrough, explain your reasoning before outputting JSON
- Keep conversational responses concise but informative
- NEVER skip the Per-IC Design Checklist. If you skip it, the design WILL have \
errors. Walk through Steps A–F for every IC before emitting JSON.
- When "design_notes" gives a specific value (e.g. 249K for 3.3V), use THAT \
value — do not guess or substitute.
- For **every** component `connections` entry, always set **pin_name** to the \
datasheet pin function (e.g. **OUT**, **IN+**, **IN-**, **VDD**, **VSS**, **SW**, \
**GND**). The schematic generator maps nets to KiCad symbols by **name** when \
possible (especially op-amps), because package pin **numbers** often differ \
between the datasheet and the KiCad library.
- Double-check voltage rails: if two power pins exist on an IC (e.g. VDD and \
VUSB), verify they connect to the correct voltage. Read "critical_notes" \
carefully.
- Use Google Search when you need datasheet information that isn't in our \
component database.
"""


# ── Project State ────────────────────────────────────────────────────────────

class ProjectState:
    """Accumulates the project JSON as the conversation progresses."""

    def __init__(self):
        self.project_name = None
        self.description = None
        self.sheets = []
        self.components = []
        self.passives = []
        self.nets = []
        self.new_components = {}
        # Track which items we've already ingested to avoid duplicates when
        # the LLM repeats the same JSON blocks (common at the end of a chat).
        self._component_keys = set()  # (sheet, ref)
        self._passive_keys = set()    # (sheet, ref)
        self._net_keys = set()        # (sheet, name)

    def ingest(self, data: dict):
        """Parse a JSON block from the LLM and merge it into state."""
        if "project_name" in data and "sheets" in data:
            self.project_name = data["project_name"]
            self.description = data.get("description", "")
            self.sheets = data["sheets"]
            return "sheets"

        if "sheet_design" in data:
            sheet = data["sheet_design"]
            # If the model never emitted the sheet list block, infer it from the
            # first per-sheet design block so generation doesn't crash.
            if not self.sheets:
                self.sheets = [{"name": sheet, "file": f"{sheet}.kicad_sch", "page": 1}]
            if not self.project_name:
                # Best-effort default so filenames are meaningful.
                self.project_name = sheet

            for comp in data.get("components", []):
                key = (comp.get("sheet", sheet), comp.get("ref"))
                if key in self._component_keys:
                    continue
                self._component_keys.add(key)
                self.components.append(comp)

            for p in data.get("passives", []):
                key = (p.get("sheet", sheet), p.get("ref"))
                if key in self._passive_keys:
                    continue
                self._passive_keys.add(key)
                self.passives.append(p)

            for n in data.get("nets", []):
                key = (n.get("sheet", sheet), n.get("name"))
                if key in self._net_keys:
                    continue
                self._net_keys.add(key)
                self.nets.append(n)
            return f"sheet:{data['sheet_design']}"

        if "cross_sheet_nets" in data:
            for n in data["cross_sheet_nets"]:
                key = (n.get("sheet", ""), n.get("name"))
                if key in self._net_keys:
                    continue
                self._net_keys.add(key)
                self.nets.append(n)
            return "cross_sheet_nets"

        return None

    def ingest_new_component(self, data: dict):
        """Store a new component definition."""
        name = data.get("name", "unknown")
        self.new_components[name] = data
        return name

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name or "Untitled",
            "description": self.description or "",
            "sheets": self.sheets,
            "components": self.components,
            "passives": self.passives,
            "nets": self.nets,
        }

    def summary(self) -> str:
        lines = [
            f"  Project:    {self.project_name or '(not set)'}",
            f"  Sheets:     {len(self.sheets)} — {[s['name'] for s in self.sheets]}",
            f"  Components: {len(self.components)} — {[c['ref'] for c in self.components]}",
            f"  Passives:   {len(self.passives)} — {[p['ref'] for p in self.passives]}",
            f"  Nets:       {len(self.nets)} — {[n['name'] for n in self.nets]}",
        ]
        if self.new_components:
            lines.append(f"  New parts:  {list(self.new_components.keys())}")
        return "\n".join(lines)


# ── JSON Extraction ──────────────────────────────────────────────────────────

def extract_json_blocks(text: str) -> list[dict]:
    """Find all ```json ... ``` blocks in the LLM response and parse them."""
    pattern = r"```json\s*\n(.*?)```"
    blocks = []
    for match in re.finditer(pattern, text, re.DOTALL):
        try:
            blocks.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass
    return blocks


def extract_new_components(text: str) -> list[dict]:
    """Find all ```new_component ... ``` blocks."""
    pattern = r"```new_component\s*\n(.*?)```"
    blocks = []
    for match in re.finditer(pattern, text, re.DOTALL):
        try:
            blocks.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass
    return blocks


# ── File I/O ─────────────────────────────────────────────────────────────────

def load_components_db() -> dict:
    with open(COMP_DB_PATH) as f:
        return json.load(f)


def _build_output_path(state: ProjectState) -> Path:
    """Choose a unique JSON filename based on the project name.

    Examples:
      LED_Blink_Project → data/llm_output_LED_Blink_Project.json
      Untitled          → data/llm_output.json, llm_output_1.json, ...
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    base_name = state.project_name or "llm_output"
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", base_name).strip("_") or "llm_output"

    # First try without a numeric suffix
    candidate = OUTPUT_DIR / f"llm_output_{slug}.json"
    if not candidate.exists():
        return candidate

    # Fall back to numbered suffixes
    idx = 1
    while True:
        candidate = OUTPUT_DIR / f"llm_output_{slug}_{idx}.json"
        if not candidate.exists():
            return candidate
        idx += 1


def save_project(state: ProjectState) -> Path:
    """Persist the current project state and return the JSON path."""
    out_path = _build_output_path(state)
    with open(out_path, "w") as f:
        json.dump(state.to_dict(), f, indent=2)
    print(f"\n  Project saved to: {out_path}")
    return out_path


def save_new_components(state: ProjectState):
    if not state.new_components:
        return
    NEW_COMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(NEW_COMP_PATH, "w") as f:
        json.dump(state.new_components, f, indent=2)
    print(f"  New components saved to: {NEW_COMP_PATH}")


# ── Main Chat Loop ───────────────────────────────────────────────────────────

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not found in .env")
        sys.exit(1)

    components_db = load_components_db()
    system_prompt = SYSTEM_PROMPT.format(
        components_db=json.dumps(components_db, indent=2)
    )

    client = genai.Client(api_key=api_key)
    google_search_tool = Tool(google_search=GoogleSearch())
    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[google_search_tool],
        ),
    )

    state = ProjectState()

    print("=" * 60)
    print("  ChipChat — Interactive PCB Design Assistant")
    print("  Type your message, or: quit/done, save, status")
    print("=" * 60)

    # Send an empty opener to trigger the LLM's greeting
    try:
        response = chat.send_message("Hello, I'd like to design a board.")
        print(f"\nAssistant: {response.text}")
        process_response(response.text, state)
    except Exception as e:
        print(f"\nERROR connecting to Gemini: {e}")
        sys.exit(1)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            user_input = "done"

        if not user_input:
            continue

        if user_input.lower() in ("quit", "done", "exit"):
            json_path = save_project(state)
            save_new_components(state)
            print(f"\n  Final state:\n{state.summary()}")

            # Automatically run the KiCad generator so the user can open the
            # result immediately in KiCad.
            try:
                print("\n  Running generate_from_llm.py to build KiCad project...")
                import subprocess

                subprocess.run(
                    [sys.executable, "scripts/generate_from_llm.py", str(json_path)],
                    cwd=ROOT,
                    check=False,
                )
            except Exception as e:
                print(f"  (Skipped KiCad generation: {e})")

            print("\n  Goodbye!")
            break

        if user_input.lower() == "save":
            save_project(state)
            save_new_components(state)
            print(f"\n  Current state:\n{state.summary()}")
            continue

        if user_input.lower() == "status":
            print(f"\n  Current state:\n{state.summary()}")
            continue

        try:
            response = chat.send_message(user_input)
            print(f"\nAssistant: {response.text}")
            process_response(response.text, state)
        except Exception as e:
            print(f"\nERROR: {e}")
            print("(You can keep chatting or type 'done' to save and exit)")


def process_response(text: str, state: ProjectState):
    """Extract any JSON blocks from the LLM response and ingest them."""
    json_blocks = extract_json_blocks(text)
    new_comp_blocks = extract_new_components(text)

    for block in json_blocks:
        result = state.ingest(block)
        if result:
            print(f"\n  [Captured: {result}]")

    for block in new_comp_blocks:
        name = state.ingest_new_component(block)
        print(f"\n  [New component saved: {name}]")


if __name__ == "__main__":
    main()
