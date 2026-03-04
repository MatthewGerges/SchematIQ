"""
Prompt Playground: iterate on Gemini prompts for project JSON generation.

Usage:
    python scripts/prompt_playground.py                          # Generate USBC sheet
    python scripts/prompt_playground.py --sheet Buck_Converter   # Different sheet
    python scripts/prompt_playground.py --sheet all              # Full project

Edit SYSTEM_PROMPT, SHEET_PROMPT, and BOARD_DESCRIPTION below to iterate.
Output is saved to data/llm_output.json after each run.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from difflib import unified_diff

from dotenv import load_dotenv  # pip install python-dotenv
from google import genai  # pip install google-genai

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

COMP_DB_PATH = ROOT.parent / "component_database" / "components.json"
DUMMY_PATH = ROOT / "data" / "project_dummy.json"
OUTPUT_PATH = ROOT / "data" / "llm_output.json"

# ── Model (see test_gemini_api.py for full list of options) ──────────────────
MODEL = "gemini-2.5-flash"

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║  PROMPT TEMPLATES — edit these to iterate on your prompts                 ║
# ╚════════════════════════════════════════════════════════════════════════════╝

SYSTEM_PROMPT = """\
You are an electronics design assistant. You generate project JSON files
for KiCad schematic generation.

## Component Database
Here are all available parts with their exact pin definitions.
You MUST use these pin numbers and pin names exactly — do not invent pins.

{components_db}

## Output JSON Schema
Your output must follow this exact structure:

{{
  "project_name": "string",
  "description": "string",

  "sheets": [
    {{"name": "SheetName", "file": "SheetName.kicad_sch", "page": 2}}
  ],

  "components": [
    {{
      "ref": "J1",
      "part": "part_name_from_component_database",
      "sheet": "SheetName",
      "note": "needs passive: describe what passives this IC needs and on which pins",
      "connections": [
        {{"pin": "A4", "pin_name": "VBUS+", "net": "NET_NAME"}}
      ]
    }}
  ],

  "nets": [
    {{
      "name": "NET_NAME",
      "type": "local | hierarchical | power",
      "sheet": "SheetName (only for local nets)",
      "connections": [
        {{"ref": "J1", "pin": "A4", "pin_name": "VBUS+", "sheet": "SheetName"}}
      ]
    }}
  ],

  "passives": [
    {{
      "ref": "R1",
      "type": "R | C | L | D | FB",
      "value": "5.1K",
      "sheet": "SheetName",
      "purpose": "why this passive exists",
      "connections": [
        {{"pin": "1", "net": "SIGNAL_NET"}},
        {{"pin": "2", "net": "GND"}}
      ]
    }}
  ]
}}

## Rules
- Every IC needs decoupling caps on its power pins (0.1uF minimum)
- I2C buses need pull-up resistors (4.7K to 3.3V rail)
- USB-C needs 5.1K CC pull-down resistors on CC1 and CC2 to GND
- TVS diodes on USB data lines and CC lines for ESD protection
- Every net must appear in BOTH component/passive "connections" AND in the "nets" list
- Passive pin 1 = signal side, pin 2 = power/ground side
- Net naming: PP_ prefix for power rails (e.g. PP_5V_VBUS, PP_3V3_OUT)
- Hierarchical nets span multiple sheets; local nets stay on one sheet
- GND is a "power" type net that spans all sheets
- Reference designators: J=connector, U=IC, R=resistor, C=capacitor, L=inductor, D=diode, FB=ferrite bead
- Number passives sequentially across all sheets (R1, R2... C1, C2... etc)
"""

SHEET_PROMPT = """\
Generate ONLY the "{sheet_name}" sheet section of the project JSON for this board:

"{board_description}"

Return a JSON object with exactly three keys:
- "components": the main IC(s) assigned to this sheet
- "passives": all passive components on this sheet (R, C, L, D, FB)
- "nets": all nets that have at least one connection on this sheet

Important: include ONLY components and passives that belong to the "{sheet_name}" sheet.
For hierarchical nets, include connections from OTHER sheets too (they connect sheets together).

Return ONLY valid JSON. No markdown fences, no explanation, no extra text.\
"""

FULL_PROJECT_PROMPT = """\
Generate a complete project JSON for this board:

"{board_description}"

Return the FULL JSON with all keys: project_name, description, sheets, components, nets, passives.
Follow the schema and rules exactly.

Return ONLY valid JSON. No markdown fences, no explanation, no extra text.\
"""

BOARD_DESCRIPTION = (
    "USB-C powered BME280 sensor board. "
    "USB-C connector provides 5V power and USB data. "
    "TPS628438 buck converter steps 5V down to 3.3V. "
    "MCP2221A bridges USB to I2C. "
    "BME280 sensor communicates over I2C at 3.3V."
)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║  END OF EDITABLE SECTION — code below handles loading, calling, diffing  ║
# ╚════════════════════════════════════════════════════════════════════════════╝


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def build_prompt(sheet_name: str, components_db: dict) -> tuple[str, str]:
    """Return (system_message, user_message) for the Gemini call."""
    system = SYSTEM_PROMPT.format(
        components_db=json.dumps(components_db, indent=2)
    )

    if sheet_name == "all":
        user = FULL_PROJECT_PROMPT.format(board_description=BOARD_DESCRIPTION)
    else:
        user = SHEET_PROMPT.format(
            sheet_name=sheet_name,
            board_description=BOARD_DESCRIPTION,
        )

    return system, user


def call_gemini(system: str, user: str) -> str:
    """Send prompt to Gemini and return raw response text."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not found in .env")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            {"role": "user", "parts": [{"text": system + "\n\n" + user}]},
        ],
    )
    return response.text


def parse_json_response(text: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown fences."""
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"\nFailed to parse JSON: {e}")
        print(f"Raw response:\n{text}")
        return None


def extract_expected(dummy: dict, sheet_name: str) -> dict:
    """Filter project_dummy.json to just the parts relevant to one sheet."""
    if sheet_name == "all":
        return dummy

    components = [c for c in dummy["components"] if c["sheet"] == sheet_name]
    passives = [p for p in dummy["passives"] if p["sheet"] == sheet_name]

    sheet_refs = {c["ref"] for c in components} | {p["ref"] for p in passives}
    nets = []
    for net in dummy["nets"]:
        has_connection_on_sheet = any(
            conn.get("sheet", net.get("sheet")) == sheet_name
            for conn in net["connections"]
        )
        if has_connection_on_sheet:
            nets.append(net)

    return {"components": components, "passives": passives, "nets": nets}


def show_diff(actual: dict, expected: dict, sheet_name: str):
    """Pretty-print both and show a unified diff."""
    actual_str = json.dumps(actual, indent=2).splitlines(keepends=True)
    expected_str = json.dumps(expected, indent=2).splitlines(keepends=True)

    diff = list(unified_diff(
        expected_str, actual_str,
        fromfile=f"expected ({sheet_name})",
        tofile=f"llm_output ({sheet_name})",
    ))

    if not diff:
        print("\n*** PERFECT MATCH! ***")
        return

    print(f"\n{'='*60}")
    print(f"DIFF: expected vs llm_output (sheet: {sheet_name})")
    print(f"{'='*60}")
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            print(f"\033[92m{line}\033[0m", end="")  # green = LLM added
        elif line.startswith("-") and not line.startswith("---"):
            print(f"\033[91m{line}\033[0m", end="")  # red = expected but missing
        elif line.startswith("@@"):
            print(f"\033[96m{line}\033[0m", end="")  # cyan = section header
        else:
            print(line, end="")


def show_summary(actual: dict, expected: dict, sheet_name: str):
    """Quick summary of what matched and what didn't."""
    print(f"\n{'='*60}")
    print(f"SUMMARY ({sheet_name})")
    print(f"{'='*60}")

    if sheet_name == "all":
        sections = ["components", "passives", "nets"]
    else:
        sections = ["components", "passives", "nets"]

    for section in sections:
        exp_items = expected.get(section, [])
        act_items = actual.get(section, [])

        if section == "components":
            exp_refs = {c["ref"] for c in exp_items}
            act_refs = {c.get("ref") for c in act_items}
        elif section == "passives":
            exp_refs = {p["ref"] for p in exp_items}
            act_refs = {p.get("ref") for p in act_items}
        elif section == "nets":
            exp_refs = {n["name"] for n in exp_items}
            act_refs = {n.get("name") for n in act_items}
        else:
            continue

        matched = exp_refs & act_refs
        missing = exp_refs - act_refs
        extra = act_refs - exp_refs

        print(f"\n  {section}: {len(act_items)} generated, {len(exp_items)} expected")
        if matched:
            print(f"    Matched:  {sorted(matched)}")
        if missing:
            print(f"    Missing:  {sorted(missing)}")
        if extra:
            print(f"    Extra:    {sorted(extra)}")


def main():
    parser = argparse.ArgumentParser(description="Prompt playground for Gemini PCB generation")
    parser.add_argument(
        "--sheet", default="USBC",
        help="Sheet to generate: USBC, Buck_Converter, USB_To_I2C, BME280_Sensor, or 'all'",
    )
    args = parser.parse_args()

    print(f"Loading component database: {COMP_DB_PATH}")
    components_db = load_json(COMP_DB_PATH)

    print(f"Loading reference project:  {DUMMY_PATH}")
    dummy = load_json(DUMMY_PATH)

    print(f"Model:  {MODEL}")
    print(f"Sheet:  {args.sheet}")
    print(f"Board:  {BOARD_DESCRIPTION[:80]}...")
    print("-" * 60)

    system, user = build_prompt(args.sheet, components_db)
    token_estimate = (len(system) + len(user)) // 4
    print(f"Prompt size: ~{token_estimate:,} tokens (system + user)")
    print("Calling Gemini...")

    raw = call_gemini(system, user)

    print(f"\n{'='*60}")
    print("RAW LLM OUTPUT")
    print(f"{'='*60}")
    print(raw)

    actual = parse_json_response(raw)
    if actual is None:
        sys.exit(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(actual, f, indent=2)
    print(f"\nSaved to: {OUTPUT_PATH}")

    expected = extract_expected(dummy, args.sheet)
    show_summary(actual, expected, args.sheet)
    show_diff(actual, expected, args.sheet)


if __name__ == "__main__":
    main()
