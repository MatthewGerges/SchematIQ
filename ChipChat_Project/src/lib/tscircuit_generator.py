"""
Generate a tscircuit project from LLM JSON.

Output:
  generated/<project_name>/tscircuit/
    - index.circuit.tsx
    - package.json
    - tsconfig.json
    - tscircuit.config.json
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


def _safe_name(value: str, fallback: str = "X") -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", (value or "").strip())
    if not s:
        return fallback
    if s[0].isdigit():
        s = f"_{s}"
    return s


def _js_string(value: str) -> str:
    return json.dumps(value)


def _normalize_resistance(value: str) -> str:
    """Convert LLM resistance strings to tscircuit-compatible format.

    tscircuit parses "10K" as 10 (drops the K). Must use lowercase SI
    suffixes: "10k", "4.7k", "100", "1M".
    """
    v = (value or "").strip()
    m = re.match(r'^([\d.]+)\s*([kKmMgG]?)(?:[oO]hm[s]?)?$', v)
    if not m:
        return v
    num, suffix = m.group(1), m.group(2).lower()
    if suffix:
        return f"{num}{suffix}"
    return num


def _normalize_capacitance(value: str) -> str:
    """Ensure capacitance values use proper SI notation for tscircuit."""
    v = (value or "").strip()
    m = re.match(r'^([\d.]+)\s*([pPnNuUmM]?)[fF]?$', v)
    if not m:
        return v
    num, prefix = m.group(1), m.group(2).lower()
    if prefix == 'u':
        return f"{num}uF"
    if prefix == 'n':
        return f"{num}nF"
    if prefix == 'p':
        return f"{num}pF"
    if prefix == 'm':
        return f"{num}mF"
    return f"{num}F"


def _infer_footprint(part: str, ref: str, pin_count: int) -> str:
    p = (part or "").upper()
    r = (ref or "").upper()
    if "CONN_ARM_JTAG_SWD_10" in p or (r.startswith("J") and pin_count >= 10):
        return "pinrow10_p1.27mm"
    if "CRYSTAL" in p or r.startswith("X"):
        return "xtal_3225"
    if "NRF5340" in p:
        return "qfn94"
    if pin_count <= 3:
        return "sot23"
    if pin_count <= 8:
        return "soic8"
    if pin_count <= 16:
        return "tssop16"
    return "qfn32"


def _infer_mpn(part: str, ref: str) -> str:
    p = (part or "").strip()
    up = p.upper()
    if up == "NRF5340_SOC":
        return "nRF5340-QKxx"
    if "CONN_ARM_JTAG_SWD_10" in up:
        return "Conn_ARM_JTAG_SWD_10"
    return p


def _collect_net_names(data: dict[str, Any]) -> list[str]:
    seen = set()
    ordered = []
    for coll in (data.get("components", []), data.get("passives", [])):
        for item in coll:
            for c in item.get("connections", []):
                net = (c.get("net") or "").strip()
                if net and net not in seen:
                    seen.add(net)
                    ordered.append(net)
    for n in data.get("nets", []):
        name = (n.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _is_gnd(net: str) -> bool:
    return (net or "").strip().upper() in {"GND", "GROUND"}


# ---------------------------------------------------------------------------
# Pin arrangement: put all GND pins on the left side of connectors so they
# render with the short ground tie style instead of hierarchical labels.
# ---------------------------------------------------------------------------

def _arrange_connector_pins(
    pin_entries: list[tuple[str, str, str]],
) -> tuple[list[str], list[str]]:
    """Split pin labels into left/right for connectors.

    GND pins go to the LEFT (tscircuit draws them with the ground-symbol
    tie-down), non-GND go to the RIGHT.
    """
    left: list[str] = []
    right: list[str] = []
    for _raw, label, net in pin_entries:
        if _is_gnd(net):
            left.append(label)
        else:
            right.append(label)
    if not left:
        half = max(1, len(right) // 2)
        left = right[:half]
        right = right[half:]
    if not right:
        right = left
        left = []
    return left, right


def _emit_generic_chip(
    lines: list[str],
    ref: str,
    part: str,
    pin_entries: list[tuple[str, str, str]],
    sch_x: float,
    sch_y: float,
) -> None:
    pins_only = [p[1] for p in pin_entries]

    if ref.upper().startswith("J"):
        left, right = _arrange_connector_pins(pin_entries)
    else:
        half = max(1, len(pins_only) // 2)
        left = pins_only[:half]
        right = pins_only[half:]
        if not right:
            right = left
            left = []

    footprint = _infer_footprint(part, ref, len(pin_entries))
    sch_width = 6 if ref.upper().startswith("J") else 10

    lines.append(f'      <chip name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} schWidth={{{sch_width}}}')
    lines.append(f"        manufacturerPartNumber={_js_string(_infer_mpn(part, ref))}")
    lines.append(f"        footprint={_js_string(footprint)}")
    lines.append("        pinLabels={{")
    for idx, (_raw_pin, label, _net) in enumerate(pin_entries, start=1):
        lines.append(f"          pin{idx}: {_js_string(label)},")
    lines.append("        }}")
    lines.append("        schPinArrangement={{")
    lines.append(
        "          leftSide: { direction: \"top-to-bottom\", pins: ["
        + ", ".join(_js_string(x) for x in left)
        + "] },"
    )
    lines.append(
        "          rightSide: { direction: \"top-to-bottom\", pins: ["
        + ", ".join(_js_string(x) for x in right)
        + "] },"
    )
    lines.append("        }}")
    lines.append("      />")

    for _raw_pin, label, net in pin_entries:
        lines.append(f'      <trace from=".{ref} > .{label}" to="net.{_safe_name(net)}" />')


def _emit_crystal_component(
    lines: list[str],
    ref: str,
    pin_entries: list[tuple[str, str, str]],
    sch_x: float,
    sch_y: float,
) -> None:
    """Emit a crystal as a 2-pin chip.

    The native <crystal> primitive renders on the schematic but does NOT
    produce a PCB footprint.  Using a <chip> with an 0805 footprint
    ensures it appears on both views.
    """
    labels = [p[1] for p in pin_entries[:2]] or ["pin1", "pin2"]
    lines.append(f'      <chip name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} schWidth={{4}}')
    lines.append(f'        manufacturerPartNumber="Crystal_32MHz"')
    lines.append(f'        footprint="0805"')
    lines.append(f"        pinLabels={{{{ pin1: {_js_string(labels[0])}, pin2: {_js_string(labels[1] if len(labels) > 1 else 'pin2')} }}}}")
    lines.append(
        f"        schPinArrangement={{{{" 
        f" leftSide: {{ direction: \"top-to-bottom\", pins: [{_js_string(labels[0])}] }},"
        f" rightSide: {{ direction: \"top-to-bottom\", pins: [{_js_string(labels[1] if len(labels) > 1 else 'pin2')}] }} }}}}"
    )
    lines.append("      />")
    for idx, (_raw_pin, label, net) in enumerate(pin_entries[:2]):
        lines.append(f'      <trace from=".{ref} > .{label}" to="net.{_safe_name(net)}" />')


def _emit_component(
    lines: list[str],
    comp: dict[str, Any],
    sch_x: float,
    sch_y: float,
) -> None:
    ref = comp.get("ref", "U1")
    part = comp.get("part", "")
    pin_entries: list[tuple[str, str, str]] = []
    for conn in comp.get("connections", []):
        raw_pin = str(conn.get("pin", "")).strip() or "P"
        raw_name = str(conn.get("pin_name", "")).strip()
        label = _safe_name(raw_name or f"P_{raw_pin}", fallback=f"P_{raw_pin}")
        net = (conn.get("net") or "").strip()
        pin_entries.append((raw_pin, label, net))

    used: set[str] = set()
    deduped: list[tuple[str, str, str]] = []
    for raw_pin, label, net in pin_entries:
        base = label
        i = 2
        while label in used:
            label = f"{base}_{i}"
            i += 1
        used.add(label)
        deduped.append((raw_pin, label, net))

    upart = (part or "").upper()
    if "CRYSTAL" in upart or ref.upper().startswith("X"):
        _emit_crystal_component(lines, ref, deduped, sch_x=sch_x, sch_y=sch_y)
    else:
        _emit_generic_chip(lines, ref, part, deduped, sch_x=sch_x, sch_y=sch_y)


def _passive_nets(passive: dict[str, Any]) -> tuple[str, str]:
    conns = {str(c.get("pin")): (c.get("net") or "").strip() for c in passive.get("connections", [])}
    return conns.get("1", ""), conns.get("2", "")


def _emit_passive_or_chip(
    lines: list[str],
    passive: dict[str, Any],
    sch_x: float,
    sch_y: float,
    rotation: str = "",
) -> None:
    ref = passive.get("ref", "P1")
    ptype = (passive.get("type") or "").strip().upper()
    value = passive.get("value", "")

    conn_by_pin = {str(c.get("pin")): (c.get("net") or "").strip() for c in passive.get("connections", [])}
    net1 = conn_by_pin.get("1", "")
    net2 = conn_by_pin.get("2", "")

    rot_attr = f' schRotation="{rotation}"' if rotation else ""

    if ptype == "R":
        rv = _normalize_resistance(value)
        lines.append(
            f'      <resistor name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} '
            f'footprint="0402" resistance={_js_string(rv)} />'
        )
        lines.append(f'      <trace from=".{ref} > .pin1" to="net.{_safe_name(net1)}" />')
        lines.append(f'      <trace from=".{ref} > .pin2" to="net.{_safe_name(net2)}" />')
        return
    if ptype == "C":
        cv = _normalize_capacitance(value)
        cap_rot = ' schRotation="90deg"'
        lines.append(
            f'      <capacitor name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} '
            f'footprint="0402" capacitance={_js_string(cv)}{cap_rot} />'
        )
        lines.append(f'      <trace from=".{ref} > .pin1" to="net.{_safe_name(net1)}" />')
        lines.append(f'      <trace from=".{ref} > .pin2" to="net.{_safe_name(net2)}" />')
        return
    if "CRYSTAL" in (passive.get("part") or "").upper() or ptype in {"X", "XTAL"}:
        lines.append(f'      <chip name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} schWidth={{4}}')
        lines.append(f'        manufacturerPartNumber="Crystal_32MHz"')
        lines.append(f'        footprint="0805"')
        lines.append(f'        pinLabels={{{{ pin1: "P1", pin2: "P2" }}}}')
        lines.append(
            '        schPinArrangement={{'
            ' leftSide: { direction: "top-to-bottom", pins: ["P1"] },'
            ' rightSide: { direction: "top-to-bottom", pins: ["P2"] } }}'
        )
        lines.append("      />")
        lines.append(f'      <trace from=".{ref} > .P1" to="net.{_safe_name(net1)}" />')
        lines.append(f'      <trace from=".{ref} > .P2" to="net.{_safe_name(net2)}" />')
        return

    lines.append(
        f'      <chip name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} schWidth={{6}} footprint="0402"'
    )
    lines.append("        pinLabels={{ pin1: \"P1\", pin2: \"P2\" }}")
    lines.append(
        "        schPinArrangement={{"
        " leftSide: { direction: \"top-to-bottom\", pins: [\"P1\"] },"
        " rightSide: { direction: \"top-to-bottom\", pins: [\"P2\"] } }}"
    )
    lines.append("      />")
    lines.append(f'      <trace from=".{ref} > .P1" to="net.{_safe_name(net1)}" />')
    lines.append(f'      <trace from=".{ref} > .P2" to="net.{_safe_name(net2)}" />')


# ---------------------------------------------------------------------------
# Layout constants for tscircuit schematic coordinates
# ---------------------------------------------------------------------------

CAP_ROW_SPACING = 4       # horizontal distance between side-by-side caps
CAP_GROUP_GAP = 6         # horizontal gap between different net-groups
PASSIVE_ROW_Y_OFFSET = 8  # below main components


def build_tscircuit_tsx(data: dict[str, Any]) -> str:
    project_name = data.get("project_name", "LLM_Project")
    sheets = data.get("sheets", [])
    all_components = data.get("components", [])
    all_passives = data.get("passives", [])

    lines: list[str] = []
    lines.append("export default () => (")
    lines.append("  <board routingDisabled>")

    for net in _collect_net_names(data):
        safe = _safe_name(net)
        lines.append(f'    <net name="{safe}" />')

    lines.append("")
    lines.append(f"    {{/* Generated from {project_name} */}}")

    for sidx, sheet in enumerate(sheets):
        sheet_name = sheet.get("name", f"Sheet{sidx+1}")
        sub_name = _safe_name(sheet_name, fallback=f"SHEET_{sidx+1}")
        y_offset = sidx * 30
        lines.append(f'    <subcircuit name="{sub_name}">')

        comps = [c for c in all_components if c.get("sheet") == sheet_name]
        passives = [p for p in all_passives if p.get("sheet") == sheet_name]

        # Place main components spaced horizontally.
        for cidx, comp in enumerate(comps):
            sch_x = -10 + cidx * 20
            sch_y = float(y_offset)
            _emit_component(lines, comp, sch_x=sch_x, sch_y=sch_y)

        # --- Capacitors: group by nets, place each group as a horizontal row ---
        caps = [p for p in passives if (p.get("type") or "").strip().upper() == "C"]
        others = [p for p in passives if (p.get("type") or "").strip().upper() != "C"]

        cap_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for p in caps:
            key = _passive_nets(p)
            cap_groups.setdefault(key, []).append(p)

        cap_base_y = y_offset + PASSIVE_ROW_Y_OFFSET
        x_cursor = -10.0
        group_row = 0
        for _nets, group in cap_groups.items():
            for cidx, p in enumerate(group):
                x = x_cursor + cidx * CAP_ROW_SPACING
                y = float(cap_base_y + group_row * 6)
                _emit_passive_or_chip(lines, p, sch_x=x, sch_y=y)
            x_cursor += len(group) * CAP_ROW_SPACING + CAP_GROUP_GAP
            if x_cursor > 30:
                x_cursor = -10.0
                group_row += 1

        # --- Non-cap passives (resistors render horizontal by default) ---
        cap_rows_used = group_row + (1 if caps else 0)
        other_base_y = cap_base_y + cap_rows_used * 6 + 4
        for pidx, p in enumerate(others):
            px = -10 + (pidx % 4) * 10
            py = float(other_base_y + (pidx // 4) * 4)
            _emit_passive_or_chip(lines, p, sch_x=px, sch_y=py)

        lines.append("    </subcircuit>")
        lines.append("")

    lines.append("  </board>")
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def write_tscircuit_project(data: dict[str, Any], output_dir: str) -> dict[str, str]:
    os.makedirs(output_dir, exist_ok=True)

    tsx_path = os.path.join(output_dir, "index.circuit.tsx")
    package_path = os.path.join(output_dir, "package.json")
    tsconfig_path = os.path.join(output_dir, "tsconfig.json")
    config_path = os.path.join(output_dir, "tscircuit.config.json")

    with open(tsx_path, "w", encoding="utf-8") as f:
        f.write(build_tscircuit_tsx(data))

    package = {
        "name": _safe_name(str(data.get("project_name", "chipchat_tscircuit")).lower()).strip("_"),
        "version": "1.0.0",
        "description": "Generated from ChipChat LLM JSON",
        "main": "index.circuit.tsx",
        "keywords": ["tscircuit", "circuit", "pcb", "electronics"],
        "scripts": {
            "dev": "tsci dev",
            "build": "tsci build",
            "snapshot": "tsci snapshot",
            "snapshot:update": "tsci snapshot --update",
            "start": "tsci dev",
            "typecheck": "tsc --noEmit",
        },
        "devDependencies": {
            "@types/react": "^19.2.14",
            "tscircuit": "^0.0.1517",
            "typescript": "^5.0.0",
        },
    }
    with open(package_path, "w", encoding="utf-8") as f:
        json.dump(package, f, indent=2)
        f.write("\n")

    tsconfig = {
        "compilerOptions": {
            "target": "ES2020",
            "module": "ESNext",
            "jsx": "react-jsx",
            "outDir": "dist",
            "rootDir": ".",
            "baseUrl": ".",
            "strict": True,
            "esModuleInterop": True,
            "moduleResolution": "node",
            "skipLibCheck": True,
            "forceConsistentCasingInFileNames": True,
            "resolveJsonModule": True,
            "sourceMap": True,
            "allowSyntheticDefaultImports": True,
            "experimentalDecorators": True,
            "types": ["tscircuit"],
        },
        "include": ["**/*.ts", "**/*.tsx"],
        "exclude": ["node_modules", "dist", ".claude"],
    }
    with open(tsconfig_path, "w", encoding="utf-8") as f:
        json.dump(tsconfig, f, indent=2)
        f.write("\n")

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "$schema": "https://cdn.jsdelivr.net/npm/@tscircuit/cli/types/tscircuit.config.schema.json"
            },
            f,
            indent=2,
        )
        f.write("\n")

    return {
        "index": tsx_path,
        "package": package_path,
        "tsconfig": tsconfig_path,
        "config": config_path,
    }
