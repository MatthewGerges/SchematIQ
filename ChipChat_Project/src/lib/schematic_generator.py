"""
Schematic generator for KiCad — reads project JSON, places components algorithmically.
"""

import json
import uuid
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.lib import kicad_api

# =============================================================================
# Constants
# =============================================================================

PIN_HALF_LEN = 3.81    # mm — pin tip offset from component center (R and C)
WIRE_STUB = 7.62       # mm — wire length from pin to label

# Algorithmic layout grid (all passives placed horizontally)
PASSIVE_X_START = 80.0       # x center of first column
PASSIVE_Y_START = 35.0       # y of first row
PASSIVE_Y_SPACING = 15.24    # mm between rows
PASSIVE_MAX_ROWS = 10        # rows per column before wrapping
PASSIVE_COL_SPACING = 80.0   # mm between columns

# Main component position
MAIN_COMP_X = 200.0
MAIN_COMP_Y = 100.0


# =============================================================================
# Symbol embedding
# =============================================================================

def _embed_device_symbol(schematic_data, symbol_type):
    """Embed a standard Device symbol (R or C) from KICAD_Library/Symbols/."""
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    SYMBOL_LIB_PATH = os.path.join(BASE_DIR, "KICAD_Library", "Symbols")

    if symbol_type == "R":
        symbol_name = "Resistor"
    elif symbol_type == "C":
        symbol_name = "Capacitor"
    else:
        return None

    symbol_file = os.path.join(SYMBOL_LIB_PATH, f"{symbol_name}.kicad_sym")
    if os.path.exists(symbol_file):
        embedded_lib_id = kicad_api.embed_symbol_from_file(
            schematic_data, symbol_name, library_path=SYMBOL_LIB_PATH
        )
        if embedded_lib_id:
            print(f"Embedded {symbol_name} symbol from file")
            return embedded_lib_id

    # Fallback inline (no UUIDs in pins — KiCad 9.x rule)
    print(f"Warning: {symbol_name}.kicad_sym not found, using inline fallback")

    if symbol_type == "R":
        symbol_def = '''(symbol "Resistor"
\t(pin_numbers (hide yes))
\t(pin_names (offset 0))
\t(exclude_from_sim no) (in_bom yes) (on_board yes)
\t(property "Reference" "R" (at 2.032 0 90)
\t\t(effects (font (size 1.27 1.27))))
\t(property "Value" "R" (at 0 0 90)
\t\t(effects (font (size 1.27 1.27))))
\t(property "Footprint" "" (at -1.778 0 90)
\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t(property "Datasheet" "~" (at 0 0 0)
\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t(symbol "Resistor_0_1"
\t\t(rectangle (start -1.016 -2.54) (end 1.016 2.54)
\t\t\t(stroke (width 0.254) (type default)) (fill (type none))))
\t(symbol "Resistor_1_1"
\t\t(pin passive line (at 0 3.81 270) (length 1.27)
\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t(number "1" (effects (font (size 1.27 1.27)))))
\t\t(pin passive line (at 0 -3.81 90) (length 1.27)
\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t(number "2" (effects (font (size 1.27 1.27))))))
)'''
    elif symbol_type == "C":
        symbol_def = '''(symbol "Capacitor"
\t(pin_numbers (hide yes))
\t(pin_names (offset 0.254))
\t(exclude_from_sim no) (in_bom yes) (on_board yes)
\t(property "Reference" "C" (at 0.635 2.54 0)
\t\t(effects (font (size 1.27 1.27)) (justify left)))
\t(property "Value" "C" (at 0.635 -2.54 0)
\t\t(effects (font (size 1.27 1.27)) (justify left)))
\t(property "Footprint" "" (at 0.9652 -3.81 0)
\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t(property "Datasheet" "~" (at 0 0 0)
\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t(symbol "Capacitor_0_1"
\t\t(polyline (pts (xy -2.032 0.762) (xy 2.032 0.762))
\t\t\t(stroke (width 0.508) (type default)) (fill (type none)))
\t\t(polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762))
\t\t\t(stroke (width 0.508) (type default)) (fill (type none))))
\t(symbol "Capacitor_1_1"
\t\t(pin passive line (at 0 3.81 270) (length 2.794)
\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t(number "1" (effects (font (size 1.27 1.27)))))
\t\t(pin passive line (at 0 -3.81 90) (length 2.794)
\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t(number "2" (effects (font (size 1.27 1.27))))))
)'''
    else:
        return
    schematic_data["lib_symbols"].append(symbol_def)


# =============================================================================
# Schematic items — add to data structure
# =============================================================================

def _add_wire(schematic_data, x1, y1, x2, y2):
    """Add a wire segment."""
    schematic_data["items"].append({
        "type": "wire",
        "pts": [(x1, y1), (x2, y2)],
        "uuid": str(uuid.uuid4())
    })


def _add_label(schematic_data, text, position, net_name=None, justify="left bottom"):
    """Add a local net label.

    justify controls text direction from the connection point:
      "left bottom"  → text extends RIGHT
      "right bottom" → text extends LEFT
    """
    schematic_data["items"].append({
        "type": "label",
        "text": text,
        "at": position,
        "justify": justify,
        "uuid": str(uuid.uuid4()),
        "net_name": net_name or text
    })


def _add_hierarchical_label(schematic_data, text, position,
                            shape="bidirectional", angle=0):
    """Add a hierarchical label (off-page connector).

    angle controls flag direction:
      0   → flag points LEFT, text RIGHT  (wire comes from LEFT)
      180 → flag points RIGHT, text LEFT  (wire comes from RIGHT)
    """
    schematic_data["items"].append({
        "type": "hierarchical_label",
        "text": text,
        "at": position,
        "angle": angle,
        "shape": shape,
        "uuid": str(uuid.uuid4())
    })


# =============================================================================
# KiCad formatters — convert data items to .kicad_sch text
# =============================================================================

def _format_wire(wire):
    pts = wire["pts"]
    return (
        f'\t(wire\n'
        f'\t\t(pts\n'
        f'\t\t\t(xy {pts[0][0]} {pts[0][1]}) (xy {pts[1][0]} {pts[1][1]})\n'
        f'\t\t)\n'
        f'\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
        f'\t\t(uuid "{wire["uuid"]}")\n'
        f'\t)'
    )


def _format_label(label):
    at = label["at"]
    justify = label.get("justify", "left bottom")
    return (
        f'\t(label "{label["text"]}"\n'
        f'\t\t(at {at[0]} {at[1]} 0)\n'
        f'\t\t(effects\n'
        f'\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
        f'\t\t\t(justify {justify})\n'
        f'\t\t)\n'
        f'\t\t(uuid "{label["uuid"]}")\n'
        f'\t)'
    )


def _format_hierarchical_label(label):
    at = label["at"]
    angle = label.get("angle", 0)
    shape = label.get("shape", "bidirectional")
    justify = "left" if angle == 0 else "right"
    return (
        f'\t(hierarchical_label "{label["text"]}"\n'
        f'\t\t(shape {shape})\n'
        f'\t\t(at {at[0]} {at[1]} {angle})\n'
        f'\t\t(effects\n'
        f'\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
        f'\t\t\t(justify {justify})\n'
        f'\t\t)\n'
        f'\t\t(uuid "{label["uuid"]}")\n'
        f'\t)'
    )


def _format_component(item):
    """Format a component instance in KiCad 9.x format."""
    text = "\t(symbol\n"
    text += f'\t\t(lib_id "{item["lib_id"]}")\n'
    text += f'\t\t(at {item["at"][0]} {item["at"][1]} {item["at"][2]})\n'
    text += '\t\t(unit 1)\n'
    text += '\t\t(exclude_from_sim no)\n'
    text += '\t\t(in_bom yes)\n'
    text += '\t\t(on_board yes)\n'
    text += '\t\t(dnp no)\n'
    text += f'\t\t(uuid "{item["uuid"]}")\n'

    ref_val = item["properties"].get("Reference", "")
    val_val = item["properties"].get("Value", "")
    footprint = item["properties"].get("Footprint", "")
    angle = item["at"][2]
    ref_y = item["at"][1] - 2.54
    val_y = item["at"][1] + 2.54

    text += f'\t\t(property "Reference" "{ref_val}"\n'
    text += f'\t\t\t(at {item["at"][0]} {ref_y} {angle})\n'
    text += '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n'
    text += '\t\t)\n'

    text += f'\t\t(property "Value" "{val_val}"\n'
    text += f'\t\t\t(at {item["at"][0]} {val_y} {angle})\n'
    text += '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n'
    text += '\t\t)\n'

    text += f'\t\t(property "Footprint" "{footprint}"\n'
    text += f'\t\t\t(at {item["at"][0]} {item["at"][1]} 0)\n'
    text += '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n'
    text += '\t\t)\n'

    text += f'\t\t(property "Datasheet" "~"\n'
    text += f'\t\t\t(at {item["at"][0]} {item["at"][1]} 0)\n'
    text += '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n'
    text += '\t\t)\n'

    for pin_num in item.get("pins", []):
        text += f'\t\t(pin "{pin_num}"\n'
        text += f'\t\t\t(uuid "{str(uuid.uuid4())}")\n'
        text += '\t\t)\n'

    text += "\t)\n"
    return text


def _save_schematic(schematic_data, file_path):
    """Save schematic data to a .kicad_sch file."""
    text = '(kicad_sch\n'
    text += f'\t(version {schematic_data["version"]})\n'
    text += f'\t(generator "{schematic_data["generator"]}")\n'
    text += '\t(generator_version "9.0")\n'
    text += f'\t(uuid "{schematic_data["uuid"]}")\n'
    text += f'\t(paper "{schematic_data["paper"]}")\n\n'

    if schematic_data["lib_symbols"]:
        text += "\t(lib_symbols\n"
        for sym in schematic_data["lib_symbols"]:
            text += f"\t\t{sym}\n"
        text += "\t)\n\n"

    for item in schematic_data["items"]:
        t = item["type"]
        if t == "symbol":
            text += _format_component(item)
        elif t == "wire":
            text += _format_wire(item) + "\n"
        elif t == "label":
            text += _format_label(item) + "\n"
        elif t == "hierarchical_label":
            text += _format_hierarchical_label(item) + "\n"

    text += ")\n"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Schematic saved to {file_path}")


# =============================================================================
# JSON loader — reads passives + net types from project JSON
# =============================================================================

def _load_sheet_passives(json_path, sheet_name):
    """Load passives and net-type info for a specific sheet.

    Returns:
        passives:   list of {ref, type, value, pin1_net, pin2_net}
        net_types:  dict  net_name → "hierarchical" | "local" | "power"
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Build net-type lookup from the "nets" section
    net_types = {}
    for net in data.get("nets", []):
        net_types[net["name"]] = net.get("type", "local")

    # Filter passives belonging to this sheet
    passives = []
    for p in data.get("passives", []):
        if p.get("sheet") != sheet_name:
            continue
        conns = {c["pin"]: c["net"] for c in p.get("connections", [])}
        passives.append({
            "ref": p["ref"],
            "type": p["type"],       # "R" or "C"
            "value": p["value"],
            "pin1_net": conns.get("1", ""),   # RIGHT side (after 90° rotation)
            "pin2_net": conns.get("2", ""),    # LEFT side
        })

    return passives, net_types


def _load_sheet_components(json_path, sheet_name):
    """Load main components (non-passives) for a sheet.

    Returns list of {ref, part, connections}.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return [c for c in data.get("components", []) if c.get("sheet") == sheet_name]


# =============================================================================
# Wiring helper — connects horizontal passive pins to net labels
# =============================================================================

def _wire_horizontal_passive(schematic_data, cx, cy, passive, net_types):
    """Wire both sides of a horizontal passive with appropriate labels.

    All passives are horizontal (angle=90):
      Pin 1 = RIGHT (+x)     Pin 2 = LEFT (-x)
    """
    pin1_x = round(cx + PIN_HALF_LEN, 2)
    pin2_x = round(cx - PIN_HALF_LEN, 2)

    # --- RIGHT side (pin 1) ---
    right_end = round(pin1_x + WIRE_STUB, 2)
    _add_wire(schematic_data, pin1_x, cy, right_end, cy)

    pin1_net = passive["pin1_net"]
    if net_types.get(pin1_net) == "hierarchical":
        # angle 0 → flag points LEFT, text extends RIGHT (wire comes from left)
        _add_hierarchical_label(schematic_data, pin1_net,
                                (right_end, cy), shape="bidirectional", angle=0)
    else:
        _add_label(schematic_data, pin1_net, (right_end, cy),
                   justify="left bottom")

    # --- LEFT side (pin 2) ---
    left_end = round(pin2_x - WIRE_STUB, 2)
    _add_wire(schematic_data, pin2_x, cy, left_end, cy)

    pin2_net = passive["pin2_net"]
    if net_types.get(pin2_net) == "hierarchical":
        # angle 180 → flag points RIGHT, text extends LEFT (wire comes from right)
        _add_hierarchical_label(schematic_data, pin2_net,
                                (left_end, cy), shape="bidirectional", angle=180)
    else:
        _add_label(schematic_data, pin2_net, (left_end, cy),
                   justify="right bottom")


# =============================================================================
# Main entry point — generate schematic from project JSON
# =============================================================================

def generate_from_json(output_path, json_path, sheet_name="BME280_Sensor"):
    """Generate a schematic sheet by reading from the project JSON.

    - Reads passives for the given sheet
    - Places them ALL horizontally in a column grid (top-left → right)
    - Adds wires + net labels (hierarchical or local based on nets section)
    - Places main components (e.g. BME280) at center-right
    """
    # 1. Load data from JSON
    passives, net_types = _load_sheet_passives(json_path, sheet_name)
    main_comps = _load_sheet_components(json_path, sheet_name)

    if not passives and not main_comps:
        print(f"Nothing found for sheet '{sheet_name}' in {json_path}")
        return

    # 2. Create schematic
    sheet_uuid = str(uuid.uuid4())
    schematic_data = kicad_api.create_schematic_data(sheet_name, sheet_uuid)

    # 3. Paths
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    SYMBOL_LIB_PATH = os.path.join(BASE_DIR, "KICAD_Library", "Symbols")

    # 4. Embed passive symbols (only the types present)
    types_needed = set(p["type"] for p in passives)
    if "R" in types_needed:
        _embed_device_symbol(schematic_data, "R")
    if "C" in types_needed:
        _embed_device_symbol(schematic_data, "C")

    # 5. Place main component(s) at center-right
    for comp in main_comps:
        part_name = comp["part"]
        lib_id = kicad_api.embed_symbol_from_file(
            schematic_data, part_name, library_path=SYMBOL_LIB_PATH
        )
        if lib_id:
            # Figure out pin count from connections
            pin_nums = [c["pin"] for c in comp.get("connections", [])]
            # Ensure we cover all pins even if some aren't in connections
            max_pin = max((int(p) for p in pin_nums if p.isdigit()), default=1)
            all_pins = [str(i) for i in range(1, max_pin + 1)]

            kicad_api.place_component(
                schematic_data, lib_id, comp["ref"], part_name,
                (MAIN_COMP_X, MAIN_COMP_Y), angle=0,
                footprint="", pins=all_pins
            )

    # 6. Place passives — all horizontal, column grid
    for i, p in enumerate(passives):
        col = i // PASSIVE_MAX_ROWS
        row = i % PASSIVE_MAX_ROWS
        px = round(PASSIVE_X_START + col * PASSIVE_COL_SPACING, 2)
        py = round(PASSIVE_Y_START + row * PASSIVE_Y_SPACING, 2)

        lib_id = "Resistor" if p["type"] == "R" else "Capacitor"
        kicad_api.place_component(
            schematic_data, lib_id, p["ref"], p["value"],
            (px, py), angle=90, pins=["1", "2"]
        )
        _wire_horizontal_passive(schematic_data, px, py, p, net_types)

    # 7. Save
    _save_schematic(schematic_data, output_path)

    print(f"\n✓ Schematic generated from {os.path.basename(json_path)}")
    print(f"  Sheet: {sheet_name}")
    if main_comps:
        for c in main_comps:
            print(f"  Component: {c['ref']} ({c['part']}) at ({MAIN_COMP_X}, {MAIN_COMP_Y})")
    print(f"  {len(passives)} passives (horizontal, column grid):")
    for p in passives:
        print(f"    {p['ref']:>3s} ({p['value']:>5s}):  {p['pin2_net']} ←[{p['ref']}]→ {p['pin1_net']}")
