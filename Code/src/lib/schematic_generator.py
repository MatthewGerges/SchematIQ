"""
Schematic generator for KiCad — reads project JSON, places components algorithmically.
"""

import json
import uuid
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.lib import kicad_api, symbol_resolver
from src.lib.symbol_aliases import apply_symbol_alias, normalize_symbol_lookup

# =============================================================================
# Constants
# =============================================================================

PIN_HALF_LEN = 3.81    # mm — pin tip offset from component center (R and C)
WIRE_STUB = 7.62       # mm — wire length from pin to label (horizontal)
WIRE_STUB_V = 10.16    # mm — wire length from pin to label (vertical, longer to clear body)

# KiCad connection grid: ERC checks endpoints against the *connection* grid.
# Default KiCad connection grid is typically 50 mil = 1.27 mm, so we snap to that.
GRID_MM = 1.27


def _snap(v: float) -> float:
    return round(round(v / GRID_MM) * GRID_MM, 6)


def _snap_pt(x: float, y: float) -> tuple[float, float]:
    return (_snap(x), _snap(y))

# Algorithmic layout grid (all passives placed horizontally)
PASSIVE_X_START = 80.01       # x center of first column (snapped by _snap anyway)
PASSIVE_Y_START = 34.29       # y of first row (27 * 1.27 mm)
PASSIVE_Y_SPACING = 15.24    # mm between rows
PASSIVE_MAX_ROWS = 10        # rows per column before wrapping
PASSIVE_COL_SPACING = 80.0   # mm between columns

# Main component baseline position (center row)
MAIN_COMP_X = 199.39         # 157 * 1.27 mm
MAIN_COMP_Y = 99.06          # 78 * 1.27 mm
# Horizontal spacing between main components when there are several
MAIN_COMP_X_SPACING = 40.0


# =============================================================================
# Symbol embedding — passive type → symbol file mapping
# =============================================================================

# Passive type → (symbol file name, placement angle for horizontal layout)
#   Symbols with VERTICAL pins (R, C, FB, L) need angle=90 to lay horizontal.
#   Symbols with HORIZONTAL pins (D) need angle=180 to keep pin 1 on the right.
PASSIVE_CONFIG = {
    "R":  {"file": "Resistor",     "angle": 90},
    "C":  {"file": "Capacitor",    "angle": 90},
    # TVS / protection diode in custom Symbols (not generic rectifier)
    "D":  {"file": "SMAJ6.5CA",    "angle": 180},
    "FB": {"file": "FerriteBead",  "angle": 90},
    "L":  {"file": "L",            "angle": 90},
    # Generic diode (OR-ing, rectifier): KiCad Device:D — pin 1 = K, pin 2 = A
    "Diode": {"packed_lib": "Device", "packed_symbol": "D", "angle": 180},
}


def _get_symbol_lib_path():
    """Return the absolute path to KICAD_Library/Symbols/."""
    base = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base, "KICAD_Library", "Symbols")


def _get_kicad_packed_symbols_dir():
    """Official kicad-symbols/ (Device, Connector_Generic, …)."""
    base = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base, "KICAD_Library", "kicad-symbols")


def _normalize_passive_type(ptype):
    """Map common LLM spellings to PASSIVE_CONFIG keys."""
    if not ptype:
        return ptype
    t = str(ptype).strip()
    low = t.lower()
    if low in ("diode", "d_schottky", "schottky", "schottky_diode", "rectifier"):
        return "Diode"
    return t


def _embed_passive_symbol(schematic_data, symbol_type):
    """Embed a passive symbol from custom Symbols/ or packed kicad-symbols/.

    Returns the lib_id string on success, or None.
    """
    symbol_type = _normalize_passive_type(symbol_type)
    cfg = PASSIVE_CONFIG.get(symbol_type)
    if not cfg:
        print(f"Warning: Unknown passive type '{symbol_type}'")
        return None

    packed_lib_name = cfg.get("packed_lib")
    packed_sym = cfg.get("packed_symbol")
    if packed_lib_name and packed_sym:
        packed_dir = _get_kicad_packed_symbols_dir()
        packed_lib_file = os.path.join(packed_dir, f"{packed_lib_name}.kicad_sym")
        if os.path.exists(packed_lib_file):
            lib_id = kicad_api.embed_symbol_from_packed_lib(
                schematic_data, packed_sym, packed_lib_file
            )
            if lib_id:
                return lib_id
        return f"{packed_lib_name}:{packed_sym}"

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
        symbol_def = '''(symbol "SchematIQ:Resistor"
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
        return "SchematIQ:Resistor"

    elif symbol_type == "C":
        symbol_def = '''(symbol "SchematIQ:Capacitor"
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
        return "SchematIQ:Capacitor"

    elif symbol_type == "L":
        # Inductor — same pin layout as resistor
        symbol_def = '''(symbol "SchematIQ:Inductor"
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
        return "SchematIQ:Inductor"

    return None


def _embed_missing_packed_symbols(schematic_data):
    """Safety-net: embed any packed-lib symbols still missing from lib_symbols.

    Scans every placed symbol's lib_id.  If the lib_id contains ':' and isn't
    already in lib_symbols, embed it using embed_symbol_from_packed_lib (which
    correctly resolves ``(extends ...)`` inheritance).
    """
    already = kicad_api._get_embedded_names(schematic_data)
    packed_dir = _get_kicad_packed_symbols_dir()
    needed: dict[str, set[str]] = {}
    for item in schematic_data["items"]:
        if item.get("type") != "symbol":
            continue
        lid = item.get("lib_id", "")
        if ":" not in lid:
            continue
        if lid in already:
            continue
        lib_nick, sym_name = lid.split(":", 1)
        needed.setdefault(lib_nick, set()).add(sym_name)

    for lib_nick, sym_names in needed.items():
        lib_file = os.path.join(packed_dir, f"{lib_nick}.kicad_sym")
        if not os.path.exists(lib_file):
            continue
        for sym_name in sym_names:
            full_id = f"{lib_nick}:{sym_name}"
            if full_id in kicad_api._get_embedded_names(schematic_data):
                continue
            result = kicad_api.embed_symbol_from_packed_lib(
                schematic_data, sym_name, lib_file
            )
            if result:
                print(f"  Safety-net embedded '{result}' into lib_symbols")


# =============================================================================
# Schematic items — add to data structure
# =============================================================================

def _add_wire(schematic_data, x1, y1, x2, y2):
    """Add a wire segment."""
    x1, y1 = _snap_pt(x1, y1)
    x2, y2 = _snap_pt(x2, y2)
    schematic_data["items"].append({
        "type": "wire",
        "pts": [(x1, y1), (x2, y2)],
        "uuid": str(uuid.uuid4())
    })


def _add_label(schematic_data, text, position, net_name=None,
               justify="left bottom", angle=0):
    """Add a local net label.

    justify controls text direction from the connection point:
      "left bottom"  → text extends RIGHT (or UP when angle=90)
      "right bottom" → text extends LEFT  (or DOWN when angle=90)
    angle rotates the label (0=horizontal, 90=vertical CCW).
    """
    position = _snap_pt(position[0], position[1])
    schematic_data["items"].append({
        "type": "label",
        "text": text,
        "at": position,
        "angle": angle,
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
    position = _snap_pt(position[0], position[1])
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
    angle = label.get("angle", 0)
    justify = label.get("justify", "left bottom")
    return (
        f'\t(label "{label["text"]}"\n'
        f'\t\t(at {at[0]} {at[1]} {angle})\n'
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
    # justify depends on which direction the flag faces
    justify = "left" if angle in (0, 90) else "right"
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
    text += '\t\t(fields_autoplaced yes)\n'
    text += f'\t\t(uuid "{item["uuid"]}")\n'

    props = item.get("properties", {})
    ref_val = props.get("Reference", "")
    val_val = props.get("Value", "")
    footprint = props.get("Footprint", "")
    datasheet = props.get("Datasheet", "~")
    description = props.get("Description", "")
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

    text += f'\t\t(property "Datasheet" "{datasheet}"\n'
    text += f'\t\t\t(at {item["at"][0]} {item["at"][1]} 0)\n'
    text += '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n'
    text += '\t\t)\n'

    if description:
        text += f'\t\t(property "Description" "{description}"\n'
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
    # Also write a minimal project-local symbol library that contains any
    # SchematIQ:* symbols we embedded. KiCad ERC warns if a lib_id nickname
    # isn't present in the project library table, even when symbols are embedded.
    out_dir = os.path.dirname(os.path.abspath(file_path))
    lib_syms_for_file: list[str] = []
    text = '(kicad_sch\n'
    text += f'\t(version {schematic_data["version"]})\n'
    text += f'\t(generator "{schematic_data["generator"]}")\n'
    text += '\t(generator_version "9.0")\n'
    text += f'\t(uuid "{schematic_data["uuid"]}")\n'
    text += f'\t(paper "{schematic_data["paper"]}")\n\n'
    
    if schematic_data["lib_symbols"]:
        # Keep all embedded symbols, including `(extends ...)` forms. Some
        # official KiCad symbols (e.g. regulators) rely on inheritance; if we
        # strip child symbols, the schematic can reference a lib_id that no
        # longer exists and KiCad may fail to open that sheet.
        lib_syms = list(schematic_data["lib_symbols"])
        if lib_syms:
            text += "\t(lib_symbols\n"
            for sym in lib_syms:
                text += f"\t\t{sym}\n"
                if '(symbol "SchematIQ:' in sym:
                    lib_syms_for_file.append(sym)
            text += "\t)\n\n"

    # Write/update the project-local SchematIQ library file.
    # (This is referenced by project_generator's sym-lib-table.)
    if lib_syms_for_file:
        lib_path = os.path.join(out_dir, "_schematiq_embedded.kicad_sym")
        with open(lib_path, "w", encoding="utf-8") as lf:
            lf.write('(kicad_symbol_lib (version 20211014) (generator "SchematIQ")\n')
            for sym in lib_syms_for_file:
                lf.write(f"  {sym}\n")
            lf.write(")\n")
    
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

    # Instances blocks help KiCad treat sheets as annotated/stable.
    text += "\t(sheet_instances\n"
    text += '\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n'
    text += "\t)\n"

    text += "\t(symbol_instances\n"
    for item in schematic_data["items"]:
        if item.get("type") != "symbol":
            continue
        props = item.get("properties", {})
        ref_val = props.get("Reference", "")
        val_val = props.get("Value", "")
        footprint = props.get("Footprint", "")
        text += f'\t\t(path "/{item["uuid"]}"\n'
        text += f'\t\t\t(reference "{ref_val}")\n'
        text += '\t\t\t(unit 1)\n'
        text += f'\t\t\t(value "{val_val}")\n'
        text += f'\t\t\t(footprint "{footprint}")\n'
        text += "\t\t)\n"
    text += "\t)\n"

    text += "\t(embedded_fonts no)\n"
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
        ptype = _normalize_passive_type(p.get("type", ""))
        # KiCad Device:D uses pin 1 = K (cathode), pin 2 = A (anode). LLMs
        # usually output pin 1 = anode (rail in), pin 2 = cathode (OR output).
        # Our horizontal layout ties JSON pin 1 → right stub, pin 2 → left;
        # swapping nets aligns LLM convention with K=1 / A=2.
        if ptype == "Diode":
            pin1_net = conns.get("2", "")
            pin2_net = conns.get("1", "")
        else:
            pin1_net = conns.get("1", "")
            pin2_net = conns.get("2", "")
        passives.append({
            "ref": p["ref"],
            "type": ptype,
            "value": p["value"],
            "pin1_net": pin1_net,   # RIGHT side (see _wire_horizontal_passive)
            "pin2_net": pin2_net,   # LEFT side
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
    cx = _snap(cx)
    cy = _snap(cy)
    pin1_x = _snap(cx + PIN_HALF_LEN)
    pin2_x = _snap(cx - PIN_HALF_LEN)

    # --- RIGHT side (pin 1) ---
    right_end = _snap(pin1_x + WIRE_STUB)
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
    left_end = _snap(pin2_x - WIRE_STUB)
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
    return _parse_symbol_pins_from_content(content)


def _parse_symbol_pins_from_content(content):
    """Parse pin tip positions from symbol content (file or single symbol block)."""
    pins = {}
    for block in content.split("(pin ")[1:]:
        at_m = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)", block)
        num_m = re.search(r'\(number\s+"([^"]+)"', block)
        name_m = re.search(r'\(name\s+"([^"]*)"', block)
        if not at_m or not num_m:
            continue
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
# Functional pin names → KiCad symbol pin numbers (op-amps, supplies)
# =============================================================================

def _functional_pin_role_from_label(label):
    """Map LLM/datasheet pin label to a semantic role, or None.

    KiCad op-amp symbols often use + / - / ~ / V+ / V- while datasheets use
    IN+ / IN- / OUT / VDD / VSS with *different* pin numbers — always prefer
    matching by this role over raw JSON pin integers when pin_name is present.
    """
    if not label:
        return None
    t = str(label).strip().upper().replace(" ", "")
    if t in ("OUT", "OUTPUT"):
        return "OP_OUT"
    if t in ("IN+", "INP", "NON-INVERTING", "NONINVERTING", "+"):
        return "OP_INP"
    if t in ("IN-", "INN", "INVERTING", "-"):
        return "OP_INN"
    if t in ("V+", "VDD", "VCC", "VS+", "VPOS"):
        return "PWR_POS"
    if t in ("V-", "VSS", "VEE", "VS-", "VNEG"):
        return "PWR_NEG"
    return None


def _symbol_pin_num_for_role(symbol_pins, role):
    """Return KiCad pin number string for this role, or None."""
    order = sorted(symbol_pins.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)

    def names_iter():
        for num in order:
            raw = str(symbol_pins[num].get("name", "")).strip()
            yield num, raw, raw.upper()

    if role == "OP_OUT":
        for num, raw, u in names_iter():
            if raw == "~" or u in ("OUT", "OUTPUT"):
                return str(num)
    elif role == "OP_INP":
        for num, raw, u in names_iter():
            if u in ("+", "IN+", "NON-INVERTING"):
                return str(num)
    elif role == "OP_INN":
        for num, raw, u in names_iter():
            if u in ("-", "IN-", "INVERTING"):
                return str(num)
    elif role == "PWR_POS":
        for num, raw, u in names_iter():
            if u in ("V+", "VDD", "VCC"):
                return str(num)
    elif role == "PWR_NEG":
        for num, raw, u in names_iter():
            if u in ("V-", "VSS", "VEE"):
                return str(num)
    return None


def _strip_kicad_pin_decorators(name):
    r"""Strip KiCad inactive-low pin names: ``~{RESET}`` → ``RESET``."""
    s = (name or "").strip()
    if s.startswith("~{") and s.endswith("}"):
        s = s[2:-1]
    return s


# Regulator / common pin-name aliases: LLM name → set of KiCad names
_PIN_NAME_ALIASES: dict[str, set[str]] = {
    "VOUT": {"VO", "VOUT", "OUT", "OUTPUT"},
    "VO":   {"VO", "VOUT", "OUT", "OUTPUT"},
    "VIN":  {"VI", "VIN", "IN", "INPUT"},
    "VI":   {"VI", "VIN", "IN", "INPUT"},
    "GND":  {"GND", "VSS", "DGND", "AGND", "EP", "EPAD", "PAD"},
    "SHIELD": {"SHIELD", "SH", "GND", "SHLD"},
}


def _pin_names_compatible(llm_name: str, kicad_name: str) -> bool:
    """Check whether an LLM-provided pin_name is compatible with a KiCad symbol
    pin name.  Handles exact match, common aliases (VO↔VOUT, VI↔VIN), and
    substring containment.
    """
    if not llm_name or not kicad_name:
        return True
    a, b = llm_name.upper(), _strip_kicad_pin_decorators(kicad_name).upper()
    if a == b:
        return True
    aliases = _PIN_NAME_ALIASES.get(a)
    if aliases and b in aliases:
        return True
    if len(a) >= 2 and len(b) >= 2 and (a in b or b in a):
        return True
    return False


def _llm_pin_matches_kicad_symbol_pin(llm_upper, kicad_raw):
    """Match LLM connector labels (VTG, SWDCLK, …) to KiCad names (VTref, SWCLK/TCK, …)."""
    if not llm_upper or not kicad_raw:
        return False
    kr = _strip_kicad_pin_decorators(kicad_raw).upper()
    if not kr:
        return False
    if llm_upper == kr:
        return True
    # Common regulator / power pin aliases
    aliases = _PIN_NAME_ALIASES.get(llm_upper)
    if aliases and kr in aliases:
        return True
    if llm_upper == "VTG" and kr == "VTREF":
        return True
    if llm_upper == "RESET_N" and "RESET" in kr:
        return True
    plain = re.sub(r"[\~\{\}]", "", kicad_raw)
    for seg in re.split(r"[/\s]+", plain):
        su = seg.strip().upper()
        if not su:
            continue
        if llm_upper == su:
            return True
        if len(su) >= 2 and len(llm_upper) >= 2 and (su in llm_upper or llm_upper in su):
            return True
    if llm_upper == "SWDCLK" and "SWCLK" in kr:
        return True
    if llm_upper == "SWDIO" and "SWDIO" in kr:
        return True
    if llm_upper == "SWO" and "SWO" in kr:
        return True
    return False


def _min_pin_count_from_connections(comp):
    """Lower bound on symbol pin count from JSON (blocks fuzzy → Conn_01x01)."""
    conns = comp.get("connections") or []
    max_n = 0
    for c in conns:
        p = str(c.get("pin", "")).strip()
        if p.isdigit():
            max_n = max(max_n, int(p))
    return max(max_n, len(conns))


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
        original_pin = str(conn["pin"])
        net_name = conn.get("net", "")
        if not net_name:
            continue

        pin_name = str(conn.get("pin_name", "")).upper()
        pin_key = None

        # ── Priority 1: JSON pin number exists in symbol with compatible name ──
        # This is the most common case and prevents mis-mapping when multiple
        # pins share the same name (e.g. two GND pins on BME280).
        if original_pin in symbol_pins:
            sym_name = str(symbol_pins[original_pin].get("name", "")).upper()
            if not pin_name or _pin_names_compatible(pin_name, sym_name):
                pin_key = original_pin

        # ── Priority 2: Name-based matching (pin number wrong / different package) ──
        if pin_key is None and pin_name:
            sym_pin1_name = str(symbol_pins.get("1", {}).get("name", "")).upper()
            sym_pin2_name = str(symbol_pins.get("2", {}).get("name", "")).upper()
            is_led_symbol = (sym_pin1_name == "K" and sym_pin2_name == "A")

            if is_led_symbol and pin_name in ("A", "ANODE") and "2" in symbol_pins:
                pin_key = "2"
            elif is_led_symbol and pin_name in ("K", "C", "CATHODE") and "1" in symbol_pins:
                pin_key = "1"
            elif sym_pin1_name == "1" and sym_pin2_name == "2":
                if pin_name in ("A", "1") and "1" in symbol_pins:
                    pin_key = "1"
                elif pin_name in ("B", "2") and "2" in symbol_pins:
                    pin_key = "2"
            elif pin_name in ("G", "GATE") and "1" in symbol_pins:
                pin_key = "1"
            elif pin_name in ("D", "DRAIN") and "2" in symbol_pins:
                pin_key = "2"
            elif pin_name in ("S", "SOURCE") and "3" in symbol_pins:
                pin_key = "3"

        if pin_key is None and pin_name:
            role = _functional_pin_role_from_label(pin_name)
            if role:
                mapped = _symbol_pin_num_for_role(symbol_pins, role)
                if mapped:
                    pin_key = mapped

        if pin_key is None and pin_name:
            for num, pdata in symbol_pins.items():
                if _llm_pin_matches_kicad_symbol_pin(pin_name, pdata.get("name", "")):
                    pin_key = str(num)
                    break

        # ── Priority 3: Fall back to numeric pin from JSON ──
        if pin_key is None:
            pin_key = original_pin

        pin_key = str(pin_key)

        if pin_key not in symbol_pins:
            name_aliases = set()
            if pin_name:
                name_aliases.add(pin_name)
            op = str(original_pin).strip().upper()
            if op:
                name_aliases.add(op)
            for num, pdata in symbol_pins.items():
                pname = str(pdata.get("name", "")).strip().upper()
                if pname and pname in name_aliases:
                    pin_key = str(num)
                    break
            if pin_key not in symbol_pins and pin_name:
                for num, pdata in symbol_pins.items():
                    if _llm_pin_matches_kicad_symbol_pin(pin_name, pdata.get("name", "")):
                        pin_key = str(num)
                        break

        if pin_key not in symbol_pins:
            continue

        pin = symbol_pins[pin_key]

        # Convert symbol coords → schematic coords
        #   X is the same (right = positive in both)
        #   Y is NEGATED (symbol: up = +, schematic: down = +)
        abs_x = _snap(comp_x + pin["x"])
        abs_y = _snap(comp_y - pin["y"])       # ← negate Y

        # Skip duplicate positions. If we truly have two different connections
        # mapped onto the same physical pin coordinate, don't draw a second
        # stub/label on top of the first (it becomes unreadable and can look
        # like two nets are shorted).
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

        # Wire extends OPPOSITE to pin's body-direction
        #   pin angle 180 → body LEFT  → wire RIGHT  (+x)
        #   pin angle 0   → body RIGHT → wire LEFT   (-x)
        #   pin angle 270 → body UP    → wire DOWN   (+y in screen)
        #   pin angle 90  → body DOWN  → wire UP     (-y in screen)
        if pin_angle == 180.0:
            dx, dy = WIRE_STUB, 0
        elif pin_angle == 0.0:
            dx, dy = -WIRE_STUB, 0
        elif pin_angle == 270.0:
            dx, dy = 0, WIRE_STUB_V         # DOWN (+y in screen)
        elif pin_angle == 90.0:
            dx, dy = 0, -WIRE_STUB_V        # UP   (-y in screen)
        else:
            dx, dy = WIRE_STUB, 0            # fallback

        end_x = _snap(abs_x + dx)
        end_y = _snap(abs_y + dy)

        _add_wire(schematic_data, abs_x, abs_y, end_x, end_y)

        # Choose label type from net_types + wire direction
        nt = net_types.get(net_name, "local")

        if dx > 0:           # wire goes RIGHT → horizontal label
            if nt == "hierarchical":
                _add_hierarchical_label(schematic_data, net_name,
                                       (end_x, end_y), angle=0)
            else:
                _add_label(schematic_data, net_name, (end_x, end_y),
                           justify="left bottom")
        elif dx < 0:          # wire goes LEFT → horizontal label
            if nt == "hierarchical":
                _add_hierarchical_label(schematic_data, net_name,
                                       (end_x, end_y), angle=180)
            else:
                _add_label(schematic_data, net_name, (end_x, end_y),
                           justify="right bottom")
        elif dy > 0:          # wire goes DOWN → vertical label, text DOWN
            if nt == "hierarchical":
                _add_hierarchical_label(schematic_data, net_name,
                                       (end_x, end_y), angle=270)
            else:
                _add_label(schematic_data, net_name, (end_x, end_y),
                           angle=90, justify="right bottom")
        elif dy < 0:          # wire goes UP → vertical label, text UP
            if nt == "hierarchical":
                _add_hierarchical_label(schematic_data, net_name,
                                       (end_x, end_y), angle=90)
            else:
                _add_label(schematic_data, net_name, (end_x, end_y),
                           angle=90, justify="left bottom")

    # ── Auto-connect unconnected pins that should have a net ──
    # Pins named Shield/GND/EP/PAD → GND; no_connect type pins → skip silently.
    connected_pins = {str(c["pin"]) for c in connections if c.get("net")}
    # Also include pins that were actually wired (name-based mapping may differ)
    already_wired = set()
    for pos in wired_positions:
        already_wired.add(pos)

    _GND_PIN_NAMES = {"GND", "VSS", "DGND", "AGND", "EP", "EPAD", "PAD",
                       "SHIELD", "SH", "SHLD"}

    for pin_num, pin_data in symbol_pins.items():
        if pin_num in connected_pins:
            continue
        pname = str(pin_data.get("name", "")).upper()
        phidden = pin_data.get("hidden", False)

        abs_x = _snap(comp_x + pin_data["x"])
        abs_y = _snap(comp_y - pin_data["y"])
        pos_key = (abs_x, abs_y)
        if pos_key in wired_positions:
            continue

        if pname in _GND_PIN_NAMES:
            pin_angle = pin_data["angle"]
            if pin_angle == 90.0:
                pin_angle = 270.0
            elif pin_angle == 270.0:
                pin_angle = 90.0
            if pin_angle == 180.0:
                dx, dy = WIRE_STUB, 0
            elif pin_angle == 0.0:
                dx, dy = -WIRE_STUB, 0
            elif pin_angle == 270.0:
                dx, dy = 0, WIRE_STUB_V
            elif pin_angle == 90.0:
                dx, dy = 0, -WIRE_STUB_V
            else:
                dx, dy = WIRE_STUB, 0
            end_x = _snap(abs_x + dx)
            end_y = _snap(abs_y + dy)
            _add_wire(schematic_data, abs_x, abs_y, end_x, end_y)
            _add_label(schematic_data, "GND", (end_x, end_y),
                       justify="left bottom" if dx >= 0 else "right bottom")
            wired_positions.add(pos_key)
            print(f"    Auto-wired pin {pin_num} ({pname}) → GND")


# =============================================================================
# Main entry point — generate schematic from project JSON
# =============================================================================

def generate_from_json(output_path, json_path, sheet_name="BME280_Sensor", *, placements: dict | None = None):
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

    placements_for_sheet = ((placements or {}).get(sheet_name) or {}).get("symbols") or {}

    # 5. Place main component(s) and wire their pins
    #
    # Previously we assumed there was a single "main" IC and stacked
    # everything at (MAIN_COMP_X, MAIN_COMP_Y). For small single-sheet
    # designs like the LED blink example this results in all connectors,
    # LEDs, FETs, etc. overlapping. Instead, spread all main components
    # horizontally on a simple row, keeping passives in their own grid.
    main_count = len(main_comps)
    main_placed = []
    used_nets: set[str] = set()
    for idx, comp in enumerate(main_comps):
        raw_part = comp["part"]
        # User-editable JSON aliases (config/symbol_aliases.json), then built-in remaps.
        part_name = apply_symbol_alias(raw_part)

        # Choose which symbol name to look up in the libraries.
        # Map common LLM-style names to real KiCad symbols:
        #
        #   - Any LED_* or LED_TH:*      → Device:LED (generic diode LED)
        #   - Any Transistor_FET:*       → Transistor_FET:Q_NMOS_GDS (generic NMOS)
        #   - Connector:1x01 / 1x02      → Connector_Generic:Conn_01x01 / Conn_01x02
        #
        # Schematic VALUE field keeps `raw_part` (what the LLM said).
        symbol_lookup = normalize_symbol_lookup(part_name)

        lib_id = None
        resolved_name = symbol_lookup
        sym_file_for_pins = None
        packed_file_and_name = None

        # Try custom Symbols folder first (exact match, for components.json parts)
        custom_path = os.path.join(SYMBOL_LIB_PATH, f"{symbol_lookup}.kicad_sym")
        if os.path.exists(custom_path):
            lib_id = kicad_api.embed_symbol_from_file(
                schematic_data, symbol_lookup, library_path=SYMBOL_LIB_PATH
            )
            if lib_id:
                sym_file_for_pins = custom_path

        # Packed official libs (e.g. "Regulator_Linear:LM1117DT-3.3").
        # Always embed using embed_symbol_from_packed_lib which resolves
        # (extends ...) inheritance correctly.
        if not lib_id and ":" in symbol_lookup:
            lib_name, sym_name = symbol_lookup.split(":", 1)
            base = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))))
            packed_lib = os.path.join(base, "KICAD_Library", "kicad-symbols", f"{lib_name}.kicad_sym")
            if os.path.exists(packed_lib):
                alt = sym_name
                maybe = symbol_resolver.resolve_in_packed_library(packed_lib, sym_name)
                if maybe:
                    alt = maybe
                resolved_name = alt
                lib_id = kicad_api.embed_symbol_from_packed_lib(
                    schematic_data, resolved_name, packed_lib
                )
                if lib_id:
                    packed_file_and_name = (packed_lib, resolved_name)

        # If still not found, resolve by name (prefix / first-6-chars) in custom + official libs
        if not lib_id:
            min_pins = _min_pin_count_from_connections(comp)
            resolved = symbol_resolver.resolve_symbol(symbol_lookup, min_pin_count=min_pins)
            if resolved:
                resolved_name, kind, path = resolved
                if kind == "packed":
                    lib_id = kicad_api.embed_symbol_from_packed_lib(
                        schematic_data, resolved_name, path
                    )
                    if lib_id:
                        packed_file_and_name = (path, resolved_name)
                else:
                    lib_id = kicad_api.embed_symbol_from_file(
                        schematic_data, resolved_name, library_path=path
                    )
                    if lib_id:
                        sym_file_for_pins = os.path.join(path, f"{resolved_name}.kicad_sym")

        if lib_id:
            # Parse symbol geometry before placing so we can (a) wire B/C/E → 1/2/3 and
            # (b) pass every pin number to KiCad (JSON may only list letter pin refs).
            symbol_pins = None
            if sym_file_for_pins and os.path.exists(sym_file_for_pins):
                symbol_pins = _parse_symbol_pins(sym_file_for_pins)
            elif packed_file_and_name:
                with open(packed_file_and_name[0], "r", encoding="utf-8") as f:
                    lib_content = f.read()
                block = kicad_api.get_symbol_block(lib_content, packed_file_and_name[1])
                if block:
                    symbol_pins = _parse_symbol_pins_from_content(block)
                # For symbols that use (extends ...), pins live in the parent.
                if not symbol_pins or len(symbol_pins) == 0:
                    extends_m = re.search(r'\(extends\s+"([^"]+)"\)', block or "")
                    if extends_m:
                        parent_block = kicad_api.get_symbol_block(lib_content, extends_m.group(1))
                        if parent_block:
                            symbol_pins = _parse_symbol_pins_from_content(parent_block)

            pin_nums = [c["pin"] for c in comp.get("connections", [])]
            if symbol_pins:
                all_pins = sorted(
                    symbol_pins.keys(),
                    key=lambda p: int(p) if str(p).isdigit() else 0,
                )
            else:
                max_pin = max(
                    (int(p) for p in pin_nums if str(p).isdigit()), default=1
                )
                all_pins = [str(i) for i in range(1, max_pin + 1)]

            # Extract properties from the embedded symbol definition.
            sym_props = kicad_api.extract_symbol_properties(schematic_data, lib_id)
            footprint = sym_props.get("Footprint", "")
            datasheet = sym_props.get("Datasheet", "~")
            description = sym_props.get("Description", "")

            # Value field: use resolved symbol name without library prefix.
            value_display = resolved_name if resolved_name else raw_part
            if ":" in value_display:
                value_display = value_display.split(":", 1)[1]

            # Placement: LLM override (if provided), otherwise deterministic row.
            if comp["ref"] in placements_for_sheet:
                p = placements_for_sheet[comp["ref"]] or {}
                comp_x = _snap(float(p.get("x")))
                comp_y = _snap(float(p.get("y")))
                comp_angle = int(p.get("angle") or 0)
            else:
                offset = idx - (main_count - 1) / 2.0
                comp_x = _snap(MAIN_COMP_X + offset * MAIN_COMP_X_SPACING)
                comp_y = _snap(MAIN_COMP_Y)
                comp_angle = 0

            kicad_api.place_component(
                schematic_data, lib_id, comp["ref"], value_display,
                (comp_x, comp_y), angle=comp_angle,
                footprint=footprint, pins=all_pins,
                datasheet=datasheet, description=description,
            )
            for c in comp.get("connections", []):
                n = (c.get("net") or "").strip()
                if n:
                    used_nets.add(n)

            if symbol_pins:
                _wire_component_pins(
                    schematic_data, comp_x, comp_y,
                    comp.get("connections", []), symbol_pins, net_types
                )
                print(f"  Wired {len(comp.get('connections', []))} pins on {comp['ref']}")
            if resolved_name != symbol_lookup:
                print(f"  Resolved lookup '{symbol_lookup}' → embedded '{resolved_name}'")
            elif symbol_lookup != raw_part:
                print(f"  Aliased '{raw_part}' → lookup '{symbol_lookup}'")
            main_placed.append(
                {
                    "ref": comp["ref"],
                    "raw_part": raw_part,
                    "x": comp_x,
                    "y": comp_y,
                }
            )
        else:
            print(
                f"  ERROR: Could not place {comp['ref']} — no symbol for "
                f"'{raw_part}' (lookup '{symbol_lookup}'). "
                f"Add a line to config/symbol_aliases.json or fix the part name."
            )

    # 6. Place passives — all horizontal, column grid
    placed_idx = 0
    for p in passives:
        ptype = p["type"]
        lib_id = passive_lib_ids.get(ptype)
        if not lib_id:
            print(f"  Skipping {p['ref']} (no symbol for type: {ptype})")
            continue

        # Placement: LLM override (if provided), otherwise deterministic grid.
        if p["ref"] in placements_for_sheet:
            pp = placements_for_sheet[p["ref"]] or {}
            px = _snap(float(pp.get("x")))
            py = _snap(float(pp.get("y")))
            angle = int(pp.get("angle") or PASSIVE_CONFIG.get(ptype, {}).get("angle", 90))
        else:
            col = placed_idx // PASSIVE_MAX_ROWS
            row = placed_idx % PASSIVE_MAX_ROWS
            px = _snap(PASSIVE_X_START + col * PASSIVE_COL_SPACING)
            py = _snap(PASSIVE_Y_START + row * PASSIVE_Y_SPACING)
            angle = PASSIVE_CONFIG.get(ptype, {}).get("angle", 90)

        kicad_api.place_component(
            schematic_data, lib_id, p["ref"], p["value"],
            (px, py), angle=angle, pins=["1", "2"]
        )
        _wire_horizontal_passive(schematic_data, px, py, p, net_types)
        if p.get("pin1_net"):
            used_nets.add(p["pin1_net"])
        if p.get("pin2_net"):
            used_nets.add(p["pin2_net"])
        placed_idx += 1

    # Add PWR_FLAG for externally-driven power nets to satisfy KiCad ERC.
    def _needs_pwr_flag(net: str) -> bool:
        n = (net or "").strip()
        if not n or n.startswith("NC_"):
            return False
        u = n.upper()
        return u == "GND" or u.startswith(("VIN", "VBUS", "VDD", "VCC"))

    power_nets = [n for n in sorted({n for n in used_nets if _needs_pwr_flag(n)})]
    if power_nets:
        base = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        power_lib = os.path.join(base, "KICAD_Library", "kicad-symbols", "power.kicad_sym")
        pwr_flag_id = None
        if os.path.exists(power_lib):
            pwr_flag_id = kicad_api.embed_symbol_from_packed_lib(
                schematic_data, "PWR_FLAG", power_lib
            )
        if pwr_flag_id:
            x0 = _snap(PASSIVE_X_START + 2 * PASSIVE_COL_SPACING)
            y0 = _snap(PASSIVE_Y_START + (PASSIVE_MAX_ROWS + 1) * PASSIVE_Y_SPACING)
            for i, net in enumerate(power_nets[:8]):
                px = x0
                py = _snap(y0 + i * 10.16)
                ref = f"FLG{i+1}"
                kicad_api.place_component(
                    schematic_data, pwr_flag_id, ref, "PWR_FLAG", (px, py), angle=0, pins=["1"]
                )
                w_end = _snap(px + WIRE_STUB)
                _add_wire(schematic_data, px, py, w_end, py)
                _add_label(schematic_data, net, (w_end, py), justify="left bottom")

    # 7. Embed any external packed-library symbols that were referenced by lib_id
    #    but not yet present in lib_symbols. Only embeds "simple" symbols (no extends).
    _embed_missing_packed_symbols(schematic_data)

    # 8. Save
    _save_schematic(schematic_data, output_path)

    print(f"\n✓ Schematic generated from {os.path.basename(json_path)}")
    print(f"  Sheet: {sheet_name}")
    for row in main_placed:
        print(
            f"  Placed: {row['ref']} ({row['raw_part']}) at ({row['x']}, {row['y']})"
        )
    print(f"  {len(passives)} passives (horizontal, column grid):")
    for p in passives:
        print(f"    {p['ref']:>3s} ({p['value']:>5s}):  {p['pin2_net']} ←[{p['ref']}]→ {p['pin1_net']}")
