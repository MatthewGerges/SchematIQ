"""
Schematic generator for KiCad — reads project JSON, places components algorithmically.
"""

import json
import uuid
import os
import re
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
# Symbol embedding — passive type → symbol file mapping
# =============================================================================

# Passive type → (symbol file name, placement angle for horizontal layout)
#   Symbols with VERTICAL pins (R, C, FB, L) need angle=90 to lay horizontal.
#   Symbols with HORIZONTAL pins (D) need angle=180 to keep pin 1 on the right.
PASSIVE_CONFIG = {
    "R":  {"file": "Resistor",     "angle": 90},
    "C":  {"file": "Capacitor",    "angle": 90},
    "D":  {"file": "SMAJ6.5CA",    "angle": 180},
    "FB": {"file": "FerriteBead",  "angle": 90},
    "L":  {"file": "L",            "angle": 90},
}


def _get_symbol_lib_path():
    """Return the absolute path to KICAD_Library/Symbols/."""
    base = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base, "KICAD_Library", "Symbols")


def _embed_passive_symbol(schematic_data, symbol_type):
    """Embed a passive symbol from KICAD_Library/Symbols/.

    Returns the lib_id string on success, or None.
    """
    cfg = PASSIVE_CONFIG.get(symbol_type)
    if not cfg:
        print(f"Warning: Unknown passive type '{symbol_type}'")
        return None

    symbol_name = cfg["file"]
    lib_path = _get_symbol_lib_path()
    sym_file = os.path.join(lib_path, f"{symbol_name}.kicad_sym")

    if os.path.exists(sym_file):
        lib_id = kicad_api.embed_symbol_from_file(
            schematic_data, symbol_name, library_path=lib_path
        )
        if lib_id:
            print(f"  Embedded {symbol_name} ({symbol_type}) from file → lib_id={lib_id}")
            return lib_id

    # Inline fallback for R, C, L (symbols that might not have a .kicad_sym)
    print(f"  Warning: {symbol_name}.kicad_sym not found, trying inline fallback")
    return _inline_passive_fallback(schematic_data, symbol_type)


def _inline_passive_fallback(schematic_data, symbol_type):
    """Inline symbol definitions for R, C, L when .kicad_sym files are missing."""
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
        schematic_data["lib_symbols"].append(symbol_def)
        return "Resistor"

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
        schematic_data["lib_symbols"].append(symbol_def)
        return "Capacitor"

    elif symbol_type == "L":
        # Inductor — same pin layout as resistor
        symbol_def = '''(symbol "Inductor"
\t(pin_numbers (hide yes))
\t(pin_names (offset 0))
\t(exclude_from_sim no) (in_bom yes) (on_board yes)
\t(property "Reference" "L" (at 2.032 0 90)
\t\t(effects (font (size 1.27 1.27))))
\t(property "Value" "L" (at 0 0 90)
\t\t(effects (font (size 1.27 1.27))))
\t(property "Footprint" "" (at -1.778 0 90)
\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t(property "Datasheet" "~" (at 0 0 0)
\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t(symbol "Inductor_0_1"
\t\t(arc (start 0 -2.54) (mid 0.6323 -1.905) (end 0 -1.27)
\t\t\t(stroke (width 0.2032) (type default)) (fill (type none)))
\t\t(arc (start 0 -1.27) (mid 0.6323 -0.635) (end 0 0)
\t\t\t(stroke (width 0.2032) (type default)) (fill (type none)))
\t\t(arc (start 0 0) (mid 0.6323 0.635) (end 0 1.27)
\t\t\t(stroke (width 0.2032) (type default)) (fill (type none)))
\t\t(arc (start 0 1.27) (mid 0.6323 1.905) (end 0 2.54)
\t\t\t(stroke (width 0.2032) (type default)) (fill (type none))))
\t(symbol "Inductor_1_1"
\t\t(pin passive line (at 0 3.81 270) (length 1.27)
\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t(number "1" (effects (font (size 1.27 1.27)))))
\t\t(pin passive line (at 0 -3.81 90) (length 1.27)
\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t(number "2" (effects (font (size 1.27 1.27))))))
)'''
        schematic_data["lib_symbols"].append(symbol_def)
        return "Inductor"

    return None


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
# Symbol pin parser — reads pin positions from .kicad_sym files
# =============================================================================

def _parse_symbol_pins(symbol_file_path):
    """Parse pin tip positions from a .kicad_sym file.

    Returns: dict  pin_number → {x, y, angle, name}
      (x, y) = pin TIP (connection point) relative to symbol center
      angle  = direction from tip INTO the body (0=right, 180=left, 270=up, 90=down)
    """
    with open(symbol_file_path, "r", encoding="utf-8") as f:
        content = f.read()

    pins = {}
    for block in content.split("(pin ")[1:]:       # skip preamble
        at_m = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)", block)
        num_m = re.search(r'\(number\s+"([^"]+)"', block)
        name_m = re.search(r'\(name\s+"([^"]*)"', block)
        if not at_m or not num_m:
            continue

        # "hide" keyword before (name ...) means the pin is invisible
        hidden = "hide" in block.split("(name")[0] if "(name" in block else False

        pins[num_m.group(1)] = {
            "x": float(at_m.group(1)),
            "y": float(at_m.group(2)),
            "angle": float(at_m.group(3)),
            "name": name_m.group(1) if name_m else "",
            "hidden": hidden,
        }

    return pins


# =============================================================================
# Component pin wiring — connects IC pins to net labels
# =============================================================================

def _wire_component_pins(schematic_data, comp_x, comp_y,
                         connections, symbol_pins, net_types):
    """Add wires + net labels for every connected pin of a component.

    Reads pin positions from the parsed symbol data.  For each pin in
    *connections*, adds a wire stub extending AWAY from the body and
    an appropriate label (hierarchical or local) at the wire end.

    IMPORTANT: Symbol .kicad_sym files use math-Y (up = positive),
    but schematics use screen-Y (down = positive).  We negate Y and
    flip vertical pin angles when converting.

    Skips hidden pins that share a position with an already-wired pin
    (e.g. duplicate GND pins on BME280).
    """
    wired_positions = set()

    for conn in connections:
        pin_num = conn["pin"]
        net_name = conn.get("net", "")
        if not net_name or pin_num not in symbol_pins:
            continue

        pin = symbol_pins[pin_num]

        # Convert symbol coords → schematic coords
        #   X is the same (right = positive in both)
        #   Y is NEGATED (symbol: up = +, schematic: down = +)
        abs_x = round(comp_x + pin["x"], 2)
        abs_y = round(comp_y - pin["y"], 2)       # ← negate Y

        # Skip duplicate positions (e.g. hidden GND pin 7 overlaps pin 1)
        pos_key = (abs_x, abs_y)
        if pos_key in wired_positions:
            continue
        wired_positions.add(pos_key)

        # Pin angle also needs Y-axis flip for vertical pins:
        #   0° and 180° (horizontal) → unchanged
        #   90° (down in symbol) → 270° (up in schematic)
        #   270° (up in symbol) → 90° (down in schematic)
        pin_angle = pin["angle"]
        if pin_angle == 90.0:
            pin_angle = 270.0
        elif pin_angle == 270.0:
            pin_angle = 90.0

        # Wire extends OPPOSITE to pin's internal direction
        #   pin angle 180 → body is LEFT of tip  → wire goes RIGHT
        #   pin angle 0   → body is RIGHT of tip → wire goes LEFT
        if pin_angle == 180.0:
            dx, dy = WIRE_STUB, 0
        elif pin_angle == 0.0:
            dx, dy = -WIRE_STUB, 0
        elif pin_angle == 270.0:
            dx, dy = 0, -WIRE_STUB
        elif pin_angle == 90.0:
            dx, dy = 0, WIRE_STUB
        else:
            dx, dy = WIRE_STUB, 0        # fallback

        end_x = round(abs_x + dx, 2)
        end_y = round(abs_y + dy, 2)

        _add_wire(schematic_data, abs_x, abs_y, end_x, end_y)

        # Choose label type from net_types + wire direction
        nt = net_types.get(net_name, "local")

        if dx > 0:           # wire goes RIGHT
            if nt == "hierarchical":
                _add_hierarchical_label(schematic_data, net_name,
                                       (end_x, end_y), angle=0)
            else:
                _add_label(schematic_data, net_name, (end_x, end_y),
                           justify="left bottom")
        elif dx < 0:          # wire goes LEFT
            if nt == "hierarchical":
                _add_hierarchical_label(schematic_data, net_name,
                                       (end_x, end_y), angle=180)
            else:
                _add_label(schematic_data, net_name, (end_x, end_y),
                           justify="right bottom")
        elif dy != 0:         # vertical wire
            _add_label(schematic_data, net_name, (end_x, end_y),
                       justify="left bottom")


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
    SYMBOL_LIB_PATH = _get_symbol_lib_path()

    # 4. Embed passive symbols — one per unique type
    types_needed = set(p["type"] for p in passives)
    passive_lib_ids = {}      # type → lib_id
    for ptype in sorted(types_needed):
        lib_id = _embed_passive_symbol(schematic_data, ptype)
        if lib_id:
            passive_lib_ids[ptype] = lib_id

    # 5. Place main component(s) at center-right and wire their pins
    for comp in main_comps:
        part_name = comp["part"]
        lib_id = kicad_api.embed_symbol_from_file(
            schematic_data, part_name, library_path=SYMBOL_LIB_PATH
        )
        if lib_id:
            # Figure out pin count from connections
            pin_nums = [c["pin"] for c in comp.get("connections", [])]
            max_pin = max((int(p) for p in pin_nums if p.isdigit()), default=1)
            all_pins = [str(i) for i in range(1, max_pin + 1)]

            kicad_api.place_component(
                schematic_data, lib_id, comp["ref"], part_name,
                (MAIN_COMP_X, MAIN_COMP_Y), angle=0,
                footprint="", pins=all_pins
            )

            # Parse pin positions from symbol file and wire connections
            sym_file = os.path.join(SYMBOL_LIB_PATH, f"{part_name}.kicad_sym")
            if os.path.exists(sym_file):
                symbol_pins = _parse_symbol_pins(sym_file)
                _wire_component_pins(
                    schematic_data, MAIN_COMP_X, MAIN_COMP_Y,
                    comp.get("connections", []), symbol_pins, net_types
                )
                print(f"  Wired {len(comp.get('connections', []))} pins on {comp['ref']}")

    # 6. Place passives — all horizontal, column grid
    placed_idx = 0
    for p in passives:
        ptype = p["type"]
        lib_id = passive_lib_ids.get(ptype)
        if not lib_id:
            print(f"  Skipping {p['ref']} (no symbol for type: {ptype})")
            continue

        col = placed_idx // PASSIVE_MAX_ROWS
        row = placed_idx % PASSIVE_MAX_ROWS
        px = round(PASSIVE_X_START + col * PASSIVE_COL_SPACING, 2)
        py = round(PASSIVE_Y_START + row * PASSIVE_Y_SPACING, 2)

        # Angle depends on symbol pin orientation (from PASSIVE_CONFIG)
        angle = PASSIVE_CONFIG.get(ptype, {}).get("angle", 90)

        kicad_api.place_component(
            schematic_data, lib_id, p["ref"], p["value"],
            (px, py), angle=angle, pins=["1", "2"]
        )
        _wire_horizontal_passive(schematic_data, px, py, p, net_types)
        placed_idx += 1

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
