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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_name(value: str, fallback: str = "X") -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", (value or "").strip())
    if not s:
        return fallback
    if s[0].isdigit():
        s = f"_{s}"
    return s


def _js_string(value: str) -> str:
    return json.dumps(value)


# Part overrides: edit config/tscircuit_part_overrides.json (MPN, footprint, etc.)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_TSC_OVERRIDES_PATH = os.path.join(_PROJECT_ROOT, "config", "tscircuit_part_overrides.json")
_TSC_OVERRIDES_CACHE: list[dict[str, Any]] | None = None


def _load_tscircuit_overrides() -> list[dict[str, Any]]:
    global _TSC_OVERRIDES_CACHE
    if _TSC_OVERRIDES_CACHE is not None:
        return _TSC_OVERRIDES_CACHE
    _TSC_OVERRIDES_CACHE = []
    if os.path.isfile(_TSC_OVERRIDES_PATH):
        try:
            with open(_TSC_OVERRIDES_PATH, encoding="utf-8") as f:
                blob = json.load(f)
            _TSC_OVERRIDES_CACHE = list(blob.get("overrides") or [])
        except (json.JSONDecodeError, OSError):
            _TSC_OVERRIDES_CACHE = []
    return _TSC_OVERRIDES_CACHE


def _override_for_part(part: str) -> dict[str, Any]:
    """First matching override row wins by longest substring match."""
    p = (part or "").upper()
    best: dict[str, Any] = {}
    best_len = 0
    for row in _load_tscircuit_overrides():
        subs = row.get("part_substrings") or []
        for s in subs:
            su = str(s).upper()
            if su and su in p and len(su) >= best_len:
                best = {k: v for k, v in row.items() if k != "part_substrings"}
                best_len = len(su)
    return best


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


def _normalize_inductance(value: str) -> str:
    v = (value or "").strip()
    m = re.match(r'^([\d.]+)\s*([pPnNuUmM]?)[hH]?$', v)
    if not m:
        return v
    num, prefix = m.group(1), m.group(2).lower()
    if prefix == "u":
        return f"{num}uH"
    if prefix == "n":
        return f"{num}nH"
    if prefix == "m":
        return f"{num}mH"
    if prefix == "p":
        return f"{num}pH"
    return f"{num}H"


def _is_gnd(net: str) -> bool:
    return (net or "").strip().upper() in {"GND", "GROUND", "VSS"}


def _infer_footprint(part: str, ref: str, pin_count: int) -> str:
    raw = part or ""
    o = _override_for_part(raw)
    if o.get("footprint"):
        return str(o["footprint"])
    p = raw.upper()
    r = (ref or "").upper()
    if "CONN_ARM_JTAG_SWD_10" in p or (r.startswith("J") and pin_count >= 10):
        return "pinrow10_p1.27mm"
    if "CRYSTAL" in p or r.startswith("X"):
        return "0805"
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
    seen: set[str] = set()
    ordered: list[str] = []
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


def _passive_nets(passive: dict[str, Any]) -> tuple[str, str]:
    conns = {str(c.get("pin")): (c.get("net") or "").strip()
             for c in passive.get("connections", [])}
    return conns.get("1", ""), conns.get("2", "")


def _emit_connections_block(
    lines: list[str],
    pin_entries: list[tuple[str, str, str]],
    indent: str = "      ",
) -> None:
    """Emit tscircuit `connections` prop for net-label-only wiring."""
    lines.append(f"{indent}  connections={{{{")
    for _raw_pin, label, net in pin_entries:
        lines.append(f"{indent}    {label}: {_js_string(f'net.{_safe_name(net)}')},")
    lines.append(f"{indent}  }}}}")


def _signal_nets_of(item: dict[str, Any]) -> set[str]:
    """Return non-GND/power net names that an item connects to."""
    nets: set[str] = set()
    for c in item.get("connections", []):
        net = (c.get("net") or "").strip()
        if net and not _is_gnd(net):
            nets.add(net)
    return nets


# ---------------------------------------------------------------------------
# Component emitters
# ---------------------------------------------------------------------------

def _emit_generic_chip(
    lines: list[str],
    ref: str,
    part: str,
    pin_entries: list[tuple[str, str, str]],
    sch_x: float,
    sch_y: float,
    indent: str = "      ",
) -> None:
    pins_only = [p[1] for p in pin_entries]
    half = max(1, len(pins_only) // 2)
    left = pins_only[:half]
    right = pins_only[half:]
    if not right:
        right = left
        left = []

    footprint = _infer_footprint(part, ref, len(pin_entries))
    sch_width = 6 if ref.upper().startswith("J") else 10

    lines.append(f'{indent}<chip name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} schWidth={{{sch_width}}}')
    lines.append(f"{indent}  manufacturerPartNumber={_js_string(_infer_mpn(part, ref))}")
    lines.append(f"{indent}  footprint={_js_string(footprint)}")
    lines.append(f"{indent}  pinLabels={{{{")
    for idx, (_raw, label, _net) in enumerate(pin_entries, start=1):
        lines.append(f"{indent}    pin{idx}: {_js_string(label)},")
    lines.append(f"{indent}  }}}}")
    lines.append(f"{indent}  schPinArrangement={{{{")
    lines.append(
        f'{indent}    leftSide: {{ direction: "top-to-bottom", pins: ['
        + ", ".join(_js_string(x) for x in left) + "] },"
    )
    lines.append(
        f'{indent}    rightSide: {{ direction: "top-to-bottom", pins: ['
        + ", ".join(_js_string(x) for x in right) + "] },"
    )
    lines.append(f"{indent}  }}}}")
    _emit_connections_block(lines, pin_entries, indent=indent)
    lines.append(f"{indent}/>")


def _emit_crystal_as_chip(
    lines: list[str],
    ref: str,
    pin_entries: list[tuple[str, str, str]],
    sch_x: float,
    sch_y: float,
    indent: str = "      ",
) -> None:
    """Render crystal as a 2-pin chip so it appears on both schematic and PCB."""
    labels = [p[1] for p in pin_entries[:2]] or ["P_1", "P_2"]
    l1, l2 = labels[0], labels[1] if len(labels) > 1 else "P_2"
    lines.append(f'{indent}<chip name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} schWidth={{4}}')
    lines.append(f'{indent}  manufacturerPartNumber="Crystal_32MHz"')
    lines.append(f'{indent}  footprint="0805"')
    lines.append(f"{indent}  pinLabels={{{{ pin1: {_js_string(l1)}, pin2: {_js_string(l2)} }}}}")
    lines.append(
        f"{indent}  schPinArrangement={{{{" 
        f' leftSide: {{ direction: "top-to-bottom", pins: [{_js_string(l1)}] }},'
        f' rightSide: {{ direction: "top-to-bottom", pins: [{_js_string(l2)}] }} }}}}'
    )
    _emit_connections_block(lines, pin_entries[:2], indent=indent)
    lines.append(f"{indent}/>")


def _emit_component(
    lines: list[str],
    comp: dict[str, Any],
    sch_x: float,
    sch_y: float,
    indent: str = "      ",
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
        _emit_crystal_as_chip(lines, ref, deduped, sch_x=sch_x, sch_y=sch_y, indent=indent)
    else:
        _emit_generic_chip(lines, ref, part, deduped, sch_x=sch_x, sch_y=sch_y, indent=indent)


def _emit_passive(
    lines: list[str],
    passive: dict[str, Any],
    sch_x: float,
    sch_y: float,
    indent: str = "      ",
) -> None:
    """Emit a passive with schOrientation and net-label traces."""
    ref = passive.get("ref", "P1")
    ptype = (passive.get("type") or "").strip().upper()
    value = passive.get("value", "")

    conn_by_pin = {str(c.get("pin")): (c.get("net") or "").strip()
                   for c in passive.get("connections", [])}
    net1 = conn_by_pin.get("1", "")
    net2 = conn_by_pin.get("2", "")

    if ptype == "R":
        rv = _normalize_resistance(value)
        lines.append(
            f'{indent}<resistor name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} '
            f'footprint="0402" resistance={_js_string(rv)} schOrientation="horizontal" />'
        )
        lines[-1] = lines[-1].replace(
            " />",
            f' connections={{{{ pin1: "{f"net.{_safe_name(net1)}"}", pin2: "{f"net.{_safe_name(net2)}"}" }}}} />',
        )
        return

    if ptype == "C":
        cv = _normalize_capacitance(value)
        lines.append(
            f'{indent}<capacitor name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} '
            f'footprint="0402" capacitance={_js_string(cv)} schOrientation="vertical" />'
        )
        lines[-1] = lines[-1].replace(
            " />",
            f' connections={{{{ pin1: "{f"net.{_safe_name(net1)}"}", pin2: "{f"net.{_safe_name(net2)}"}" }}}} />',
        )
        return

    if ptype == "L":
        ind = _normalize_inductance(value)
        lines.append(
            f'{indent}<inductor name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} '
            f'footprint="1210" inductance={_js_string(ind)} schOrientation="horizontal" />'
        )
        lines[-1] = lines[-1].replace(
            " />",
            f' connections={{{{ pin1: "{f"net.{_safe_name(net1)}"}", pin2: "{f"net.{_safe_name(net2)}"}" }}}} />',
        )
        return

    if ptype in {"DIODE", "D"} or "DIODE" in ptype:
        is_sch = "SCHOTTKY" in value.upper()
        sch_flag = " schottky={true}" if is_sch else ""
        lines.append(
            f'{indent}<diode name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} '
            f'footprint="sod123"{sch_flag} schOrientation="horizontal" />'
        )
        lines[-1] = lines[-1].replace(
            " />",
            f' connections={{{{ anode: "{f"net.{_safe_name(net1)}"}", cathode: "{f"net.{_safe_name(net2)}"}" }}}} />',
        )
        return

    if "CRYSTAL" in (passive.get("part") or "").upper() or ptype in {"X", "XTAL"}:
        l1, l2 = "P_1", "P_2"
        lines.append(f'{indent}<chip name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} schWidth={{4}}')
        lines.append(f'{indent}  manufacturerPartNumber="Crystal_32MHz"')
        lines.append(f'{indent}  footprint="0805"')
        lines.append(f'{indent}  pinLabels={{{{ pin1: "{l1}", pin2: "{l2}" }}}}')
        lines.append(
            f'{indent}  schPinArrangement={{{{' 
            f' leftSide: {{ direction: "top-to-bottom", pins: ["{l1}"] }},'
            f' rightSide: {{ direction: "top-to-bottom", pins: ["{l2}"] }} }}}}'
        )
        lines.append(
            f'{indent}  connections={{{{ {l1}: "net.{_safe_name(net1)}", {l2}: "net.{_safe_name(net2)}" }}}}'
        )
        lines.append(f"{indent}/>")
        return

    # Fallback: generic 2-pin chip
    lines.append(
        f'{indent}<chip name="{ref}" schX={{{sch_x}}} schY={{{sch_y}}} schWidth={{6}} footprint="0402"'
    )
    lines.append(f'{indent}  pinLabels={{{{ pin1: "P1", pin2: "P2" }}}}')
    lines.append(
        f'{indent}  schPinArrangement={{{{' 
        f' leftSide: {{ direction: "top-to-bottom", pins: ["P1"] }},'
        f' rightSide: {{ direction: "top-to-bottom", pins: ["P2"] }} }}}}'
    )
    lines.append(
        f'{indent}  connections={{{{ P1: "net.{_safe_name(net1)}", P2: "net.{_safe_name(net2)}" }}}}'
    )
    lines.append(f"{indent}/>")


# ---------------------------------------------------------------------------
# Passive-to-component grouping
# ---------------------------------------------------------------------------

def _group_passives_by_parent(
    comps: list[dict[str, Any]],
    passives: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Assign each passive to its most-related main component (by shared
    signal nets, ignoring GND/power).  Falls back to first component."""
    comp_sig_nets: dict[str, set[str]] = {}
    for comp in comps:
        comp_sig_nets[comp["ref"]] = _signal_nets_of(comp)

    groups: dict[str, list[dict[str, Any]]] = {c["ref"]: [] for c in comps}
    fallback = comps[0]["ref"] if comps else "__NONE__"

    for p in passives:
        p_nets = _signal_nets_of(p)
        best_ref = fallback
        best_overlap = 0
        for ref, c_nets in comp_sig_nets.items():
            overlap = len(p_nets & c_nets)
            if overlap > best_overlap:
                best_overlap = overlap
                best_ref = ref
        groups.setdefault(best_ref, []).append(p)

    return groups


# ---------------------------------------------------------------------------
# Annotation helpers
# ---------------------------------------------------------------------------

_COMPONENT_ANNOTATIONS: dict[str, str] = {
    "NRF5340": "This is the MCU",
}


def _annotation_for(part: str) -> str | None:
    up = (part or "").upper()
    for key, text in _COMPONENT_ANNOTATIONS.items():
        if key in up:
            return text
    return None


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

COMP_H_SPACING = 14   # horizontal gap between main ICs
PASSIVE_Y_GAP = 7     # vertical offset from IC row to passive area
CAP_H_SPACING = 5     # horizontal gap between side-by-side caps
OTHER_H_SPACING = 8   # horizontal gap between non-cap passives
OTHER_V_OFFSET = 6    # vertical offset of resistors below caps


def build_tscircuit_tsx(data: dict[str, Any]) -> str:
    project_name = data.get("project_name", "LLM_Project")
    sheets = data.get("sheets", [])
    all_components = data.get("components", [])
    all_passives = data.get("passives", [])

    lines: list[str] = []
    lines.append("export default () => (")
    lines.append("  <board routingDisabled>")

    for net in _collect_net_names(data):
        lines.append(f'    <net name="{_safe_name(net)}" />')

    lines.append("")
    lines.append(f"    {{/* Generated from {project_name} */}}")

    for sidx, sheet in enumerate(sheets):
        sheet_name = sheet.get("name", f"Sheet{sidx+1}")
        sub_name = _safe_name(sheet_name, fallback=f"SHEET_{sidx+1}")
        y_base = sidx * 12
        # Prefer net labels on long schematic routes (tscircuit still auto-routes wires).
        lines.append(
            f'    <subcircuit name="{sub_name}" schTraceAutoLabelEnabled={{true}}>'
        )

        comps = [c for c in all_components if c.get("sheet") == sheet_name]
        passives = [p for p in all_passives if p.get("sheet") == sheet_name]

        # --- Row of main components ---
        comp_x_positions: dict[str, float] = {}
        for cidx, comp in enumerate(comps):
            sx = float(-10 + cidx * COMP_H_SPACING)
            sy = float(y_base)
            comp_x_positions[comp["ref"]] = sx
            _emit_component(lines, comp, sch_x=sx, sch_y=sy)

            annotation = _annotation_for(comp.get("part", ""))
            if annotation:
                lines.append(
                    f'      <schematictext text={_js_string(annotation)} '
                    f'schX={{{sx + 6}}} schY={{{sy - 3}}} fontSize={{0.3}} />'
                )

        # --- Passives in one compact grouped cluster near mains ---
        if comps and passives:
            x_values = list(comp_x_positions.values())
            center_x = (min(x_values) + max(x_values)) / 2 if x_values else -10.0
            base_x = center_x - 10
            passive_y = float(y_base + PASSIVE_Y_GAP)

            caps = [p for p in passives if (p.get("type") or "").upper() == "C"]
            others = [p for p in passives if (p.get("type") or "").upper() != "C"]

            for ci, cap in enumerate(caps):
                cx = base_x + (ci % 5) * CAP_H_SPACING
                cy = passive_y + (ci // 5) * 3
                _emit_passive(lines, cap, sch_x=cx, sch_y=cy)

            other_base_y = passive_y + 6 + (len(caps) // 5) * 3
            for oi, other in enumerate(others):
                ox = base_x + (oi % 4) * OTHER_H_SPACING
                oy = other_base_y + (oi // 4) * 3
                _emit_passive(lines, other, sch_x=ox, sch_y=oy)

        elif passives:
            px_base = -10.0
            py_base = float(y_base + PASSIVE_Y_GAP)
            for pi, p in enumerate(passives):
                px = px_base + (pi % 6) * CAP_H_SPACING
                py = py_base + (pi // 6) * 5
                _emit_passive(lines, p, sch_x=px, sch_y=py)

        lines.append("    </subcircuit>")
        lines.append("")

    lines.append("  </board>")
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Project scaffolding
# ---------------------------------------------------------------------------

def write_tscircuit_project(data: dict[str, Any], output_dir: str) -> dict[str, str]:
    os.makedirs(output_dir, exist_ok=True)

    tsx_path = os.path.join(output_dir, "index.circuit.tsx")
    package_path = os.path.join(output_dir, "package.json")
    tsconfig_path = os.path.join(output_dir, "tsconfig.json")
    config_path = os.path.join(output_dir, "tscircuit.config.json")

    with open(tsx_path, "w", encoding="utf-8") as f:
        f.write(build_tscircuit_tsx(data))

    package = {
        "name": _safe_name(str(data.get("project_name", "schematiq_tscircuit")).lower()).strip("_"),
        "version": "1.0.0",
        "description": "Generated from SchematIQ LLM JSON",
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
