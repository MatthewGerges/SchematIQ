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
from google import genai  # pip install google-genai
from google.genai import types

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

COMP_DB_PATH = ROOT.parent / "component_database" / "components.json"
OUTPUT_PATH = ROOT / "data" / "llm_output.json"
NEW_COMP_PATH = ROOT / "data" / "llm_components.json"

# ── Model (see test_gemini_api.py for full list of options) ──────────────────
MODEL = "gemini-2.5-flash"

# ── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an electronics design assistant helping a user create a KiCad schematic project.

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
5. Once the user approves the sheet structure, go sheet by sheet. For each sheet:
   a. Explain what the core IC does and how it typically connects in this application
   b. Use your electronics knowledge to determine all needed passives \
(decoupling caps, pull-ups, pull-downs, ESD protection, filter components, etc.)
   c. Name nets intuitively — you choose meaningful names
   d. When ready, output the complete sheet design as a fenced JSON code block
6. After all sheets are done, generate:
   - The cross-sheet (hierarchical) nets that connect signals between sheets
   - The GND power net with all ground connections across all sheets
   - Output these as a final JSON code block
7. Ask the user if they'd like to review or modify anything, then tell them to \
type "done" to save.

## Component Database

Here are the parts currently in our KiCad library with exact pin definitions.
When you use one of these parts, you MUST use the exact pin numbers and pin names \
listed here.

If you need a part NOT in this database, you may still use it. Provide a full \
component definition in the same JSON format (with pins, manufacturer, etc.) \
inside a fenced code block tagged as ```new_component so we can add it to the \
library later.

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
- Reference designators: J=connector, U=IC, R=resistor, C=capacitor, \
L=inductor, D=diode, FB=ferrite bead
- Number passives sequentially across ALL sheets (R1, R2... C1, C2... not \
restarting per sheet)
- Use your own electronics knowledge for design decisions — do not ask the user \
for technical details you should know as an EE
- If the user wants a walkthrough, explain your reasoning before outputting JSON
- Keep conversational responses concise but informative
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

    def ingest(self, data: dict):
        """Parse a JSON block from the LLM and merge it into state."""
        if "project_name" in data and "sheets" in data:
            self.project_name = data["project_name"]
            self.description = data.get("description", "")
            self.sheets = data["sheets"]
            return "sheets"

        if "sheet_design" in data:
            self.components.extend(data.get("components", []))
            self.passives.extend(data.get("passives", []))
            self.nets.extend(data.get("nets", []))
            return f"sheet:{data['sheet_design']}"

        if "cross_sheet_nets" in data:
            self.nets.extend(data["cross_sheet_nets"])
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


def save_project(state: ProjectState):
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(state.to_dict(), f, indent=2)
    print(f"\n  Project saved to: {OUTPUT_PATH}")


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
    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
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
            save_project(state)
            save_new_components(state)
            print(f"\n  Final state:\n{state.summary()}")
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
