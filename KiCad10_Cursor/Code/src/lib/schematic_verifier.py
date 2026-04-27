"""
Round-trip verification: parse a generated .kicad_sch back to a connectivity
model and compare it against the original design JSON to detect discrepancies
(missing components, orphaned labels, disconnected pins).

Usage from CLI:
    python -m src.lib.schematic_verifier data/llm_output_Foo.json generated/Foo/Sheet.kicad_sch

Usage from Python:
    from src.lib.schematic_verifier import verify_schematic
    report = verify_schematic(json_path, sch_path)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


# ── KiCad .kicad_sch parser ─────────────────────────────────────────────────

_GRID_SNAP = 1.27


def _snap(v: float) -> float:
    return round(round(v / _GRID_SNAP) * _GRID_SNAP, 4)


def _parse_placed_symbols(text: str) -> list[dict[str, Any]]:
    """Extract placed symbol instances (not lib_symbols definitions)."""
    symbols: list[dict[str, Any]] = []
    # Match top-level (symbol blocks that have (lib_id ...) — these are
    # placed instances; lib_symbols definitions don't have lib_id.
    for m in re.finditer(
        r'^\t\(symbol\n'
        r'\t\t\(lib_id "([^"]+)"\)\n'
        r'\t\t\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)',
        text, re.MULTILINE,
    ):
        lib_id = m.group(1)
        x, y, angle = float(m.group(2)), float(m.group(3)), float(m.group(4))
        # Find the Reference property in this symbol block
        block_start = m.start()
        # Find the closing of this symbol block
        depth = 0
        idx = block_start
        block_end = len(text)
        for i in range(block_start, len(text)):
            if text[i] == '(':
                depth += 1
            elif text[i] == ')':
                depth -= 1
                if depth == 0:
                    block_end = i + 1
                    break
        block = text[block_start:block_end]

        ref_m = re.search(r'\(property "Reference" "([^"]+)"', block)
        val_m = re.search(r'\(property "Value" "([^"]+)"', block)
        ref = ref_m.group(1) if ref_m else "?"
        value = val_m.group(1) if val_m else ""

        # Extract pin instance numbers
        pin_nums = re.findall(r'\(pin "([^"]+)"', block)

        symbols.append({
            "ref": ref,
            "lib_id": lib_id,
            "x": x, "y": y, "angle": angle,
            "value": value,
            "pins": pin_nums,
        })
    return symbols


def _parse_labels(text: str) -> list[dict[str, Any]]:
    """Extract all (label ...) and (hierarchical_label ...) entries."""
    labels: list[dict[str, Any]] = []
    for m in re.finditer(
        r'\t\((?:label|hierarchical_label) "([^"]+)"\n'
        r'\t\t\(at ([-\d.]+) ([-\d.]+)',
        text, re.MULTILINE,
    ):
        labels.append({
            "net": m.group(1),
            "x": float(m.group(2)),
            "y": float(m.group(3)),
        })
    return labels


def _parse_wires(text: str) -> list[tuple[float, float, float, float]]:
    """Extract all (wire ...) endpoints."""
    wires: list[tuple[float, float, float, float]] = []
    for m in re.finditer(
        r'\(wire\s*\n\s*\(pts\s*\n?\s*'
        r'\(xy ([-\d.]+) ([-\d.]+)\)\s*\(xy ([-\d.]+) ([-\d.]+)\)',
        text,
    ):
        wires.append((
            float(m.group(1)), float(m.group(2)),
            float(m.group(3)), float(m.group(4)),
        ))
    return wires


def parse_kicad_sch(sch_path: str | Path) -> dict[str, Any]:
    """Parse a .kicad_sch file into a structured dict."""
    text = Path(sch_path).read_text(encoding="utf-8")
    return {
        "symbols": _parse_placed_symbols(text),
        "labels": _parse_labels(text),
        "wires": _parse_wires(text),
    }


# ── Build connectivity from wire/label positions ────────────────────────────

def _build_wire_graph(wires: list[tuple[float, float, float, float]]) -> dict[tuple[float, float], set[tuple[float, float]]]:
    """Map each wire endpoint to the set of points it's directly connected to."""
    graph: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for x1, y1, x2, y2 in wires:
        p1, p2 = (_snap(x1), _snap(y1)), (_snap(x2), _snap(y2))
        graph.setdefault(p1, set()).add(p2)
        graph.setdefault(p2, set()).add(p1)
    return graph


def _flood_fill(graph: dict, start: tuple[float, float]) -> set[tuple[float, float]]:
    """Return all points reachable from start via wires."""
    visited: set[tuple[float, float]] = set()
    stack = [start]
    while stack:
        p = stack.pop()
        if p in visited:
            continue
        visited.add(p)
        for neighbor in graph.get(p, set()):
            if neighbor not in visited:
                stack.append(neighbor)
    return visited


def _nets_at_point(
    point: tuple[float, float],
    label_map: dict[tuple[float, float], list[str]],
    wire_graph: dict,
) -> set[str]:
    """Return net names reachable from a point via wires + labels."""
    reachable = _flood_fill(wire_graph, point)
    reachable.add(point)
    nets: set[str] = set()
    for p in reachable:
        for name in label_map.get(p, []):
            nets.add(name)
    return nets


# ── Verification logic ──────────────────────────────────────────────────────

def verify_schematic(
    json_path: str | Path,
    sch_path: str | Path,
    *,
    sheet_name: str | None = None,
) -> dict[str, Any]:
    """Compare an input design JSON against a generated .kicad_sch.

    Returns a report dict with:
      - missing_components: refs in JSON not placed in schematic
      - extra_components: refs in schematic not in JSON (excluding PWR_FLAG)
      - missing_nets: net names in JSON that have no label in schematic
      - pin_errors: list of {ref, pin, expected_net, actual_nets} for pins
        where the expected net is not reachable
      - ok: True if no errors
    """
    with open(json_path, encoding="utf-8") as f:
        design = json.load(f)

    parsed = parse_kicad_sch(sch_path)

    # Build lookup structures
    sch_refs = {s["ref"]: s for s in parsed["symbols"]}
    label_map: dict[tuple[float, float], list[str]] = {}
    for lb in parsed["labels"]:
        key = (_snap(lb["x"]), _snap(lb["y"]))
        label_map.setdefault(key, []).append(lb["net"])
    wire_graph = _build_wire_graph(parsed["wires"])

    all_label_nets = {lb["net"] for lb in parsed["labels"]}

    # Collect expected components + passives
    json_components = list(design.get("components", []))
    json_passives = list(design.get("passives", []))
    if sheet_name:
        json_components = [c for c in json_components if c.get("sheet") == sheet_name]
        json_passives = [p for p in json_passives if p.get("sheet") == sheet_name]
    json_items = json_components + json_passives
    json_refs = {item["ref"] for item in json_items}

    report: dict[str, Any] = {
        "missing_components": [],
        "extra_components": [],
        "missing_nets": [],
        "pin_errors": [],
        "summary": {},
    }

    # 1. Missing components
    for ref in sorted(json_refs):
        if ref not in sch_refs:
            report["missing_components"].append(ref)

    # 2. Extra components (ignore PWR_FLAG / FLG)
    for ref in sorted(sch_refs.keys()):
        if ref not in json_refs and not ref.startswith("FLG"):
            report["extra_components"].append(ref)

    # 3. Missing net labels
    expected_nets: set[str] = set()
    for item in json_items:
        for conn in item.get("connections", []):
            net = conn.get("net", "")
            if net and not net.startswith("NC"):
                expected_nets.add(net)
    for net in sorted(expected_nets):
        if net not in all_label_nets:
            report["missing_nets"].append(net)

    # 4. Pin connectivity check — for each component pin, verify the expected
    #    net is reachable via wires from the pin's physical position.
    # We need the embedded symbol pin positions for this; parse them from the
    # kicad_sch lib_symbols section.
    sch_text = Path(sch_path).read_text(encoding="utf-8")

    for item in json_items:
        ref = item["ref"]
        if ref not in sch_refs:
            continue
        sym = sch_refs[ref]
        comp_x, comp_y = sym["x"], sym["y"]

        # Get pin positions from the embedded symbol definition
        lib_id = sym["lib_id"]
        sym_pins = _parse_symbol_pin_positions(sch_text, lib_id)

        for conn in item.get("connections", []):
            expected_net = conn.get("net", "")
            pin_num = str(conn.get("pin", ""))
            if not expected_net or expected_net.startswith("NC"):
                continue

            if pin_num not in sym_pins:
                continue

            pin_x, pin_y = sym_pins[pin_num]
            # Convert from symbol coords to schematic coords (negate Y)
            abs_x = _snap(comp_x + pin_x)
            abs_y = _snap(comp_y - pin_y)

            actual_nets = _nets_at_point((abs_x, abs_y), label_map, wire_graph)
            if expected_net not in actual_nets:
                report["pin_errors"].append({
                    "ref": ref,
                    "pin": pin_num,
                    "expected_net": expected_net,
                    "actual_nets": sorted(actual_nets) if actual_nets else [],
                })

    n_errors = (
        len(report["missing_components"])
        + len(report["missing_nets"])
        + len(report["pin_errors"])
    )
    report["ok"] = n_errors == 0
    report["summary"] = {
        "components_expected": len(json_refs),
        "components_placed": len(sch_refs) - sum(1 for r in sch_refs if r.startswith("FLG")),
        "missing_components": len(report["missing_components"]),
        "missing_nets": len(report["missing_nets"]),
        "pin_errors": len(report["pin_errors"]),
    }
    return report


def _parse_symbol_pin_positions(
    sch_text: str, lib_id: str,
) -> dict[str, tuple[float, float]]:
    """Extract pin number → (x, y) from the lib_symbols definition in the schematic."""
    pins: dict[str, tuple[float, float]] = {}
    # Find the lib_symbols block for this lib_id
    escaped = re.escape(lib_id)
    pattern = rf'\(symbol "{escaped}"\s*\n'
    m = re.search(pattern, sch_text)
    if not m:
        return pins

    # Find the extent of this symbol definition
    start = m.start()
    depth = 0
    end = len(sch_text)
    for i in range(start, len(sch_text)):
        if sch_text[i] == '(':
            depth += 1
        elif sch_text[i] == ')':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    block = sch_text[start:end]

    for pin_block in block.split("(pin ")[1:]:
        at_m = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)", pin_block)
        num_m = re.search(r'\(number\s+"([^"]+)"', pin_block)
        if not at_m or not num_m:
            continue
        # Only take visible (non-hidden) pins, or all pins
        pins[num_m.group(1)] = (float(at_m.group(1)), float(at_m.group(2)))
    return pins


# ── Pretty printing ─────────────────────────────────────────────────────────

def format_report(report: dict[str, Any]) -> str:
    """Format a verification report for terminal output."""
    lines: list[str] = []
    s = report["summary"]
    ok = report["ok"]

    lines.append("")
    lines.append("=" * 60)
    if ok:
        lines.append("  ROUND-TRIP VERIFICATION: ALL OK")
    else:
        lines.append("  ROUND-TRIP VERIFICATION: ISSUES FOUND")
    lines.append(f"  Components: {s['components_placed']}/{s['components_expected']} placed")
    lines.append("=" * 60)

    if report["missing_components"]:
        lines.append(f"\n  MISSING COMPONENTS ({len(report['missing_components'])}):")
        for ref in report["missing_components"]:
            lines.append(f"    - {ref} not placed in schematic")

    if report["missing_nets"]:
        lines.append(f"\n  MISSING NET LABELS ({len(report['missing_nets'])}):")
        for net in report["missing_nets"]:
            lines.append(f"    - \"{net}\" has no label in schematic")

    if report["pin_errors"]:
        lines.append(f"\n  DISCONNECTED PINS ({len(report['pin_errors'])}):")
        for err in report["pin_errors"]:
            actual = ", ".join(err["actual_nets"]) if err["actual_nets"] else "nothing"
            lines.append(
                f"    - {err['ref']} pin {err['pin']}: "
                f"expected \"{err['expected_net']}\", "
                f"connected to [{actual}]"
            )

    if report["extra_components"]:
        lines.append(f"\n  EXTRA COMPONENTS ({len(report['extra_components'])}):")
        for ref in report["extra_components"]:
            lines.append(f"    - {ref} in schematic but not in JSON")

    lines.append("")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.lib.schematic_verifier <design.json> <sheet.kicad_sch> [sheet_name]")
        sys.exit(1)
    json_p = sys.argv[1]
    sch_p = sys.argv[2]
    sheet = sys.argv[3] if len(sys.argv) > 3 else None
    report = verify_schematic(json_p, sch_p, sheet_name=sheet)
    print(format_report(report))
    sys.exit(0 if report["ok"] else 1)
