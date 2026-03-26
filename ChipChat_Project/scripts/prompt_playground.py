"""
Interactive LLM Design Playground: multi-turn chat with Gemini for PCB design.

The LLM acts as an electronics design assistant — uses its own EE knowledge,
asks about your requirements, and builds up a project JSON sheet by sheet.

Usage:
    cd ChipChat_Project
    source .venv/bin/activate
    pip install -r requirements.txt
    python scripts/prompt_playground.py

Commands during chat:
    help, ?      — command reference
    save         — write project JSON (same path on later saves)
    status       — summary of accumulated design
    gen, generate, build, done — save + run KiCad + tscircuit generators (stay in chat)
    check        — symbol validation + 2-LLM electrical review; JSON report + in-chat summary
    validate     — KiCad symbol resolution only (fast, no LLM)
    review       — 2-LLM electrical review only → reports/
    repair       — LLM symbol repair on saved JSON, then reload
    reload       — reload project JSON from disk (after editing in Cursor)
    bye          — save + generate + exit
    quit, exit   — save JSON only + exit (no generator)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv  # pip install python-dotenv
try:
    from google import genai  # pip install google-genai
except ImportError:
    print("ImportError: google-genai is required. From ChipChat_Project directory:")
    print("  source .venv/bin/activate")
    print("  pip install google-genai python-dotenv")
    sys.exit(1)
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.theme import Theme
except ImportError:
    print("ImportError: rich is required for the playground UI.")
    print("  pip install rich")
    sys.exit(1)
from google.genai import types
from google.genai.types import GoogleSearch, Tool

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

PLAYGROUND_THEME = Theme(
    {
        "info": "dim cyan",
        "warn": "yellow",
        "err": "bold red",
        "cmd": "bold magenta",
        "accent": "bold bright_cyan",
    }
)

def llm_intent_is_schematic_check(client: any, model: str, user_text: str) -> bool:
    """
    Decide whether the user is asking for a schematic check.

    This intentionally does NOT rely on keyword presence. Instead, we ask the LLM
    to classify the intent, then we trigger the expensive `check` pipeline.
    """
    try:
        classifier_prompt = (
            "You are an intent classifier for an electronics design assistant.\n"
            "Return STRICT JSON only with this schema:\n"
            '{ "schematic_check_requested": boolean, "reason": string }\n'
            "\n"
            "Set schematic_check_requested=true if the user is asking you to:\n"
            "- review the schematic/board for errors\n"
            "- run an ERC-like check\n"
            "- run the assistant's schematic check pipeline (JSON report)\n"
            "\n"
            "Otherwise set it to false.\n"
            "\n"
            f"User message: {user_text!r}\n"
        )
        resp = client.models.generate_content(model=model, contents=classifier_prompt)
        text = (resp.text or "").strip()
        if not text:
            return False
        parsed = json.loads(text)
        return bool(parsed.get("schematic_check_requested"))
    except Exception:
        return False

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
7. After the design is captured, remind them they can type **gen** (or **done**) to rebuild \
KiCad/tscircuit, and **check** to run symbol validation plus electrical review (report JSON \
under `reports/`), without leaving the chat.

## Schematic iteration & debugging (anytime)

The user may keep chatting **after** schematics are generated. They might say:
- A pin shows connected in the project JSON but **not** on the KiCad schematic (or the opposite).
- A symbol looks wrong or pins are swapped.

When that happens:
1. Reason about **pin_name vs pin number**: our generator maps nets using **pin_name** when \
possible; KiCad library pin numbers can differ from the datasheet.
2. Check **part** / library symbol choice — wrong symbol → wrong pinout.
3. Propose **concrete fixes** as normal fenced ```json blocks (same schema as before) so \
they can be merged, or describe exact field edits (ref, pin, net, part).

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
- **No-connect pins:** If a pin is intentionally unused, either (1) assign a net name
  starting with **NC_** (e.g. `NC_SWO`, `NC_J1_7`) — only that pin on that net — or
  (2) **omit** that pin from the component's `connections` array entirely. Do **not** use
  vague net names that look like real signals. The checker treats single-connection **NC_***
  nets as intentional, not floating.
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
        # Once set, subsequent saves overwrite this file (stable path for regen / repair).
        self.output_json_path: Path | None = None
        # Track which items we've already ingested to avoid duplicates when
        # the LLM repeats the same JSON blocks (common at the end of a chat).
        self._component_keys = set()  # (sheet, ref)
        self._passive_keys = set()    # (sheet, ref)
        self._net_keys = set()        # (sheet, name)

    @classmethod
    def from_dict(cls, data: dict) -> ProjectState:
        """Replace state from a saved JSON file (e.g. after repair or manual edit)."""
        s = cls()
        s.project_name = data.get("project_name")
        s.description = data.get("description", "")
        s.sheets = list(data.get("sheets", []))
        s.components = list(data.get("components", []))
        s.passives = list(data.get("passives", []))
        s.nets = list(data.get("nets", []))
        for c in s.components:
            sh = c.get("sheet")
            s._component_keys.add((sh, c.get("ref")))
        for p in s.passives:
            sh = p.get("sheet")
            s._passive_keys.add((sh, p.get("ref")))
        for n in s.nets:
            sh = n.get("sheet", "")
            s._net_keys.add((sh, n.get("name")))
        return s

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
    with open(COMP_DB_PATH, encoding="utf-8") as f:
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
    if state.output_json_path is not None:
        out_path = state.output_json_path
    else:
        out_path = _build_output_path(state)
        state.output_json_path = out_path
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2)
    return out_path


def save_new_components(state: ProjectState, console: Console) -> None:
    if not state.new_components:
        return
    NEW_COMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(NEW_COMP_PATH, "w", encoding="utf-8") as f:
        json.dump(state.new_components, f, indent=2)
    console.print(f"[dim]New component defs → {NEW_COMP_PATH}[/]")


def print_help(console: Console) -> None:
    table = Table(show_header=True, header_style="bold bright_white", title="Playground commands")
    table.add_column("Command", style="magenta", no_wrap=True)
    table.add_column("Action")
    for cmd, desc in (
        ("help, ?", "Show this table"),
        ("save", "Write JSON (reuses the same file on later saves)"),
        ("status", "Sheet / component / net counts"),
        ("gen, done, build", "Save + run KiCad + tscircuit — [bold]stay in chat[/]"),
        ("check", "Symbols + 2-LLM electrical review — full JSON in [bold]reports/[/]"),
        ("validate", "KiCad symbol resolution only (fast, no Gemini)"),
        ("review", "Electrical review only (same LLM pass as [magenta]check[/])"),
        ("repair", "LLM symbol repair on saved JSON, reload state"),
        ("reload", "Reload JSON from disk (after editing in Cursor)"),
        ("load PATH", "Open a different llm_output*.json as the working project"),
        ("bye", "Save + generate + exit"),
        ("quit", "Save JSON only + exit (no build)"),
    ):
        table.add_row(cmd, desc)
    console.print(table)
    console.print(
        Panel(
            "[bold]Schematic check[/]\n"
            "Type [magenta]check[/] (or phrases like “schematic check”) for **symbol validation** "
            "plus **2-LLM electrical review**. Full JSON: [i]reports/<project>_schematic_check.json[/]. "
            "Use [magenta]validate[/] for symbols only (no Gemini).\n\n"
            "[bold]KiCad and live updates[/]\n"
            "KiCad does not continuously watch schematic files. After each [cmd]gen[/], "
            "close the affected schematic tab(s) and reopen them from the project tree, "
            "or use [i]File → Revert[/] if your KiCad version offers it.\n\n"
            "[bold]JSON vs schematic mismatches[/]\n"
            "Describe the issue in plain language; the assistant can reason about "
            "[i]pin_name[/] vs pin number, symbol choice, and nets, and emit corrected JSON blocks.\n\n"
            "[bold]load PATH[/]\n"
            "Swaps the in-memory project to another JSON file. Gemini still has the old "
            "conversation context — restart the script if you want a fully fresh thread.",
            title="Tips",
            border_style="dim",
        )
    )


def _generated_paths(state: ProjectState) -> tuple[Path, Path]:
    pname = (state.project_name or "LLM_Project").strip() or "LLM_Project"
    gen = ROOT / "generated" / pname
    return gen / f"{pname}.kicad_pro", gen / "tscircuit"


def run_generate(console: Console, state: ProjectState) -> int:
    json_path = save_project(state)
    save_new_components(state, console)
    console.print(
        Panel(str(json_path), title="[green]Saved project JSON[/]", border_style="green")
    )
    console.print("[dim]Running[/] [magenta]generate_from_llm.py --target both[/][dim]…[/]\n")
    rc = subprocess.run(
        [sys.executable, "scripts/generate_from_llm.py", "--target", "both", str(json_path)],
        cwd=ROOT,
    ).returncode
    kicad_pro, tsci = _generated_paths(state)
    console.print()
    console.print(
        Panel(
            f"[bold]KiCad[/]\n[accent]{kicad_pro}[/]\n\n"
            f"[bold]tscircuit[/]\n[accent]{tsci}[/]\n\n"
            "[dim]Tip: run [magenta]gen[/] again any time after edits.[/]",
            title="Build" if rc == 0 else "Build (exit code {})".format(rc),
            border_style="cyan" if rc == 0 else "red",
        )
    )
    return rc


def cmd_review(console: Console, state: ProjectState) -> None:
    from src.lib.electrical_review_llm import run_two_llm_review

    json_path = save_project(state)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    console.print("[dim]Running 2-LLM electrical review…[/]")
    report = run_two_llm_review(data)
    report_dir = ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{json_path.stem}_electrical_review.json"
    with open(report_path, "w", encoding="utf-8") as rf:
        json.dump(report, rf, indent=2)
        rf.write("\n")
    merged = report.get("merged", {})
    hs = merged.get("human_summary") or {}
    headline = hs.get("headline", "")
    fc = merged.get("finding_counts") or {}
    body = f"[accent]{report_path}[/]\n\n"
    if headline:
        body += f"{headline}\n"
    body += (
        f"\n[dim]errors / warnings / info:[/] "
        f"{fc.get('error', 0)} / {fc.get('warning', 0)} / {fc.get('info', 0)}"
    )
    console.print(Panel(body, title="Electrical review", border_style="blue"))


def _compact_check_json_for_chat(
    consolidated: dict,
    report_path: Path,
    *,
    max_findings: int = 35,
) -> dict:
    """Smaller object to print in-terminal; full detail stays on disk."""
    merged = consolidated["electrical_review"].get("merged") or {}
    findings = merged.get("findings") or []
    compact: dict = {
        "full_report_file": str(report_path),
        "source_project_json": consolidated["source_project_json"],
        "symbol_validation": consolidated["symbol_validation"],
        "electrical": {
            "finding_counts": merged.get("finding_counts"),
            "human_summary": merged.get("human_summary"),
            "findings": findings[:max_findings],
        },
    }
    compact["electrical"]["info_bundle"] = merged.get("info")
    if len(findings) > max_findings:
        compact["electrical"]["findings_truncated"] = len(findings) - max_findings
    return compact


def cmd_schematic_check(console: Console, state: ProjectState) -> None:
    """Symbol preflight + 2-LLM review; one JSON file + Rich summary + JSON snippet in chat."""
    from src.lib.electrical_review_llm import run_two_llm_review
    from src.lib.symbol_preflight import validate_components_in_llm_data

    json_path = save_project(state)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    console.print("[dim]1/2 KiCad symbol resolution (local)…[/]")
    sym_errors = validate_components_in_llm_data(data, print_ok=False)
    sym_ok = len(sym_errors) == 0

    console.print("[dim]2/2 2-LLM electrical review (Gemini)…[/]")
    er_report = run_two_llm_review(data)

    report_dir = ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{json_path.stem}_schematic_check.json"

    consolidated = {
        "check_generated_at": datetime.now(timezone.utc).isoformat(),
        "source_project_json": str(json_path.resolve()),
        "symbol_validation": {
            "ok": sym_ok,
            "error_count": len(sym_errors),
            "errors": sym_errors,
        },
        "electrical_review": er_report,
    }
    with open(report_path, "w", encoding="utf-8") as wf:
        json.dump(consolidated, wf, indent=2)
        wf.write("\n")

    merged = er_report.get("merged") or {}
    hs = merged.get("human_summary") or {}
    fc = merged.get("finding_counts") or {}
    ne, nw, ni = int(fc.get("error") or 0), int(fc.get("warning") or 0), int(fc.get("info") or 0)

    sym_panel = (
        "[green]All component symbols resolve.[/]"
        if sym_ok
        else "[yellow]" + "\n".join(sym_errors[:20]) + ("[/]\n[dim]…[/]" if len(sym_errors) > 20 else "[/]")
    )
    console.print(Panel(sym_panel, title="Symbol validation", border_style="green" if sym_ok else "yellow"))

    el_lines = [
        f"[accent]{report_path}[/]",
        "",
        f"[bold]{hs.get('headline', '(no headline)')}[/]",
        f"[dim]Electrical counts — errors / warnings / info:[/] {ne} / {nw} / {ni}",
    ]
    if hs.get("must_fix"):
        el_lines.append("\n[red bold]Must fix[/]")
        el_lines.extend(f"  • {m}" for m in hs["must_fix"][:8])
    if hs.get("double_check"):
        el_lines.append("\n[yellow bold]Double-check[/]")
        el_lines.extend(f"  • {m}" for m in hs["double_check"][:8])
    console.print(Panel("\n".join(el_lines), title="Schematic check summary", border_style="blue"))

    compact = _compact_check_json_for_chat(consolidated, report_path)
    json_text = json.dumps(compact, indent=2)
    console.print(
        Panel(
            Syntax(json_text, "json", theme="monokai", word_wrap=True),
            title="[bold]Summary JSON[/] (full report on disk — path above)",
            border_style="cyan",
        )
    )


def cmd_validate_symbols(console: Console, state: ProjectState) -> None:
    """Fast symbol resolution only; small JSON under reports/."""
    from src.lib.symbol_preflight import validate_components_in_llm_data

    json_path = save_project(state)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    sym_errors = validate_components_in_llm_data(data, print_ok=False)
    sym_ok = len(sym_errors) == 0

    report_dir = ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{json_path.stem}_symbol_validation.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_project_json": str(json_path.resolve()),
        "ok": sym_ok,
        "error_count": len(sym_errors),
        "errors": sym_errors,
    }
    with open(report_path, "w", encoding="utf-8") as wf:
        json.dump(payload, wf, indent=2)
        wf.write("\n")

    body = f"[accent]{report_path}[/]\n\n"
    body += "[green]OK — all symbols resolve.[/]" if sym_ok else "[yellow]" + "\n".join(sym_errors) + "[/]"
    console.print(Panel(body, title="Symbol validation", border_style="green" if sym_ok else "yellow"))
    console.print(
        Panel(
            Syntax(json.dumps(payload, indent=2), "json", theme="monokai", word_wrap=True),
            title="JSON (also saved to file)",
            border_style="cyan",
        )
    )


def cmd_repair(console: Console, state: ProjectState) -> ProjectState:
    from src.lib.symbol_preflight import find_unresolved_components
    from src.lib.symbol_repair_llm import repair_symbols_with_llm

    path = save_project(state)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    failures = find_unresolved_components(data)
    if not failures:
        console.print("[info]All symbols resolve — nothing to repair.[/]")
        return state
    console.print(f"[info]Repairing [bold]{len(failures)}[/] unresolved symbol(s)…[/]")
    data, report = repair_symbols_with_llm(data, failures, dry_run=False)
    with open(path, "w", encoding="utf-8") as wf:
        json.dump(data, wf, indent=2)
        wf.write("\n")
    applied = report.get("applied") or []
    rej = report.get("rejected") or []
    detail = json.dumps({"applied": applied, "rejected": rej}, indent=2)
    if len(detail) > 6000:
        detail = detail[:6000] + "\n…"
    console.print(Panel(detail, title="Symbol repair", border_style="green"))
    ns = ProjectState.from_dict(data)
    ns.output_json_path = path
    console.print("[dim]State reloaded. Run[/] [magenta]gen[/] [dim]to rebuild schematics.[/]")
    return ns


def cmd_reload(console: Console, state: ProjectState) -> ProjectState:
    if state.output_json_path is None or not state.output_json_path.is_file():
        console.print("[warn]No JSON on disk yet — use[/] [magenta]save[/] [warn]first.[/]")
        return state
    with open(state.output_json_path, encoding="utf-8") as f:
        data = json.load(f)
    ns = ProjectState.from_dict(data)
    ns.output_json_path = state.output_json_path
    console.print(f"[info]Reloaded[/] [accent]{state.output_json_path}[/]")
    return ns


def cmd_load(console: Console, arg: str) -> tuple[ProjectState | None, str]:
    raw = arg.strip().strip('"').strip("'")
    if not raw:
        return None, "Usage: [magenta]load[/] path/to/llm_output_Something.json"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    else:
        path = path.resolve()
    if not path.is_file():
        return None, f"[err]File not found:[/] {path}"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ns = ProjectState.from_dict(data)
    ns.output_json_path = path
    return ns, f"[info]Loaded[/] [accent]{path}[/]"


def render_assistant(console: Console, text: str) -> None:
    console.print()
    console.print(
        Panel(
            Markdown(text),
            title="[bold cyan]Assistant[/]",
            border_style="cyan",
            padding=(0, 1),
        )
    )


def print_status(console: Console, state: ProjectState) -> None:
    console.print(Panel(state.summary(), title="Project status", border_style="blue"))


# ── Main Chat Loop ───────────────────────────────────────────────────────────

def main() -> None:
    console = Console(theme=PLAYGROUND_THEME)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        console.print("[err]GEMINI_API_KEY not found in .env[/]")
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

    console.print(
        Panel.fit(
            "[bold accent]ChipChat[/] — interactive schematic design\n"
            "[dim]Type[/] [magenta]check[/] [dim]for symbol + electrical review ·[/] [magenta]help[/] [dim]for all commands[/]",
            border_style="bright_cyan",
        )
    )

    try:
        response = chat.send_message("Hello, I'd like to design a board.")
        render_assistant(console, response.text or "")
        process_response(console, response.text or "", state)
    except Exception as e:
        console.print(f"[err]ERROR connecting to Gemini:[/] {e}")
        sys.exit(1)

    while True:
        try:
            user_input = Prompt.ask("\n[bold green]You[/]").strip()
        except EOFError:
            user_input = "quit"
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted — still in session. Type[/] [magenta]quit[/] [dim]to exit.[/]")
            continue

        if not user_input:
            continue

        parts = user_input.split(maxsplit=1)
        cmd0 = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        if cmd0 in ("help", "?"):
            print_help(console)
            continue

        if cmd0 == "save":
            p = save_project(state)
            save_new_components(state, console)
            console.print(Panel(f"[accent]{p}[/]", title="Saved", border_style="green"))
            print_status(console, state)
            continue

        if cmd0 == "status":
            print_status(console, state)
            continue

        if cmd0 in ("gen", "generate", "build", "done"):
            run_generate(console, state)
            console.print("[dim]You can keep chatting or run[/] [magenta]gen[/] [dim]again after edits.[/]")
            continue

        if cmd0 in ("check", "schematic-check", "schematic_check"):
            cmd_schematic_check(console, state)
            continue

        if cmd0 == "validate":
            cmd_validate_symbols(console, state)
            continue

        if cmd0 == "review":
            cmd_review(console, state)
            continue

        if cmd0 == "repair":
            state = cmd_repair(console, state)
            continue

        if cmd0 == "reload":
            state = cmd_reload(console, state)
            continue

        if cmd0 == "load":
            ns, msg = cmd_load(console, rest)
            if ns is None:
                console.print(msg)
            else:
                console.print(msg)
                state = ns
            continue

        if cmd0 == "bye":
            save_new_components(state, console)
            print_status(console, state)
            run_generate(console, state)
            console.print("[accent]Goodbye![/]")
            break

        if cmd0 in ("quit", "exit"):
            p = save_project(state)
            save_new_components(state, console)
            console.print(Panel(f"[accent]{p}[/]\n\n{state.summary()}", title="Saved (no build)", border_style="yellow"))
            console.print("[accent]Goodbye![/]")
            break

        if llm_intent_is_schematic_check(client, MODEL, user_input):
            cmd_schematic_check(console, state)
            continue

        try:
            response = chat.send_message(user_input)
            render_assistant(console, response.text or "")
            process_response(console, response.text or "", state)
        except Exception as e:
            console.print(f"[err]ERROR:[/] {e}")
            console.print("[dim]You can retry or type[/] [magenta]help[/][dim].[/]")


def process_response(console: Console, text: str, state: ProjectState) -> None:
    """Extract any JSON blocks from the LLM response and ingest them."""
    json_blocks = extract_json_blocks(text)
    new_comp_blocks = extract_new_components(text)

    for block in json_blocks:
        result = state.ingest(block)
        if result:
            console.print(f"[dim]Captured:[/] [cyan]{result}[/]")

    for block in new_comp_blocks:
        name = state.ingest_new_component(block)
        console.print(f"[dim]New component:[/] [cyan]{name}[/]")


if __name__ == "__main__":
    main()
