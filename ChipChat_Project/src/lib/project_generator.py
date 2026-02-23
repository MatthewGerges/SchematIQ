"""Generate KiCad project files (.kicad_pro and root .kicad_sch) from project JSON."""

import json
import uuid
import os


# ─── Layout constants for root schematic ─────────────────────────────────────
PIN_SPACING = 5.08       # mm between hierarchical pins on sheet box
BOX_W = 50.0             # sheet box width
BOX_H_MIN = 20.0         # minimum sheet box height
BOX_MARGIN = 5.08        # space inside box above first pin
Y_GAP = 15.0             # vertical gap between sheet boxes
X_LEFT = 30.0            # left edge of first sheet box
Y_START = 30.0           # top of first sheet box
WIRE_LEN = 10.0          # wire stub from pin to label


def generate_root_schematic(json_path, output_dir, project_name=None):
    """Generate root .kicad_sch with hierarchical sheet boxes + pins from JSON.

    Reads the sheets list and nets from the project JSON.  For every
    hierarchical net, a pin is placed on each sheet box that touches
    that net.  Short wires + net labels connect matching pins.

    Returns (output_path, root_uuid, sheet_uuids)
      sheet_uuids: list of (uuid_str, sheet_name) for .kicad_pro
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if project_name is None:
        project_name = data.get("project_name", "Project")

    sheets_def = data["sheets"]
    nets = data.get("nets", [])

    # Build mapping: sheet_name → [hierarchical net names that touch it]
    sheet_hier_pins = {s["name"]: [] for s in sheets_def}
    for net in nets:
        if net.get("type") != "hierarchical":
            continue
        touched = set()
        for conn in net.get("connections", []):
            s = conn.get("sheet", "")
            if s in sheet_hier_pins:
                touched.add(s)
        for s in sorted(touched):          # sorted for deterministic order
            sheet_hier_pins[s].append(net["name"])

    # Compute sheet positions
    root_uuid = str(uuid.uuid4())
    sheet_items = []
    y_cursor = Y_START

    for s_def in sheets_def:
        name = s_def["name"]
        pins = sheet_hier_pins.get(name, [])
        box_h = max(BOX_H_MIN, len(pins) * PIN_SPACING + 2 * BOX_MARGIN)

        sheet_items.append({
            "uuid": str(uuid.uuid4()),
            "at": (X_LEFT, round(y_cursor, 2)),
            "size": (BOX_W, round(box_h, 2)),
            "name": name,
            "file": s_def["file"],
            "page": s_def["page"],
            "pins": pins,
        })
        y_cursor += box_h + Y_GAP

    # ── Build KiCad s-expression ──────────────────────────────────────────
    t = '(kicad_sch\n'
    t += '\t(version 20250114)\n'
    t += '\t(generator "ChipChat_Gemini")\n'
    t += '\t(generator_version "9.0")\n'
    t += f'\t(uuid "{root_uuid}")\n'
    t += '\t(paper "A4")\n'
    t += '\t(lib_symbols)\n\n'

    # Sheet boxes
    for sh in sheet_items:
        sx, sy = sh["at"]
        sw, sh_h = sh["size"]

        t += '\t(sheet\n'
        t += f'\t\t(at {sx} {sy})\n'
        t += f'\t\t(size {sw} {sh_h})\n'
        t += '\t\t(exclude_from_sim no)\n'
        t += '\t\t(in_bom yes)\n'
        t += '\t\t(on_board yes)\n'
        t += '\t\t(dnp no)\n'
        t += '\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type solid)\n\t\t)\n'
        t += '\t\t(fill\n\t\t\t(color 0 0 0 0.0000)\n\t\t)\n'
        t += f'\t\t(uuid "{sh["uuid"]}")\n'

        # Sheetname property
        t += f'\t\t(property "Sheetname" "{sh["name"]}"\n'
        t += f'\t\t\t(at {sx} {round(sy - 0.68, 2)} 0)\n'
        t += '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
        t += '\t\t\t\t)\n\t\t\t\t(justify left bottom)\n\t\t\t)\n'
        t += '\t\t)\n'

        # Sheetfile property
        t += f'\t\t(property "Sheetfile" "{sh["file"]}"\n'
        t += f'\t\t\t(at {sx} {round(sy + sh_h + 0.2, 2)} 0)\n'
        t += '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
        t += '\t\t\t\t)\n\t\t\t\t(justify left top)\n\t\t\t)\n'
        t += '\t\t)\n'

        # Hierarchical pins on RIGHT edge of box
        pin_y = round(sy + BOX_MARGIN, 2)
        for pin_name in sh["pins"]:
            pin_x = round(sx + sw, 2)
            t += f'\t\t(pin "{pin_name}" bidirectional\n'
            t += f'\t\t\t(at {pin_x} {pin_y} 0)\n'
            t += '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
            t += '\t\t\t\t)\n\t\t\t\t(justify left)\n\t\t\t)\n'
            t += f'\t\t\t(uuid "{str(uuid.uuid4())}")\n'
            t += '\t\t)\n'
            pin_y = round(pin_y + PIN_SPACING, 2)

        t += '\t)\n\n'

    # Wires + net labels at each hierarchical pin (connects matching names)
    for sh in sheet_items:
        sx, sy = sh["at"]
        sw = sh["size"][0]
        pin_y = round(sy + BOX_MARGIN, 2)
        for pin_name in sh["pins"]:
            pin_x = round(sx + sw, 2)
            wire_end = round(pin_x + WIRE_LEN, 2)

            # Wire stub
            t += f'\t(wire\n'
            t += f'\t\t(pts\n\t\t\t(xy {pin_x} {pin_y}) (xy {wire_end} {pin_y})\n\t\t)\n'
            t += '\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
            t += f'\t\t(uuid "{str(uuid.uuid4())}")\n'
            t += '\t)\n'

            # Net label
            t += f'\t(label "{pin_name}"\n'
            t += f'\t\t(at {wire_end} {pin_y} 0)\n'
            t += '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n'
            t += '\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n'
            t += f'\t\t(uuid "{str(uuid.uuid4())}")\n'
            t += '\t)\n'

            pin_y = round(pin_y + PIN_SPACING, 2)

    # Sheet instances (page numbering)
    t += '\n\t(sheet_instances\n'
    t += '\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n'
    for sh in sheet_items:
        t += f'\t\t(path "/{sh["uuid"]}"\n'
        t += f'\t\t\t(page "{sh["page"]}")\n'
        t += '\t\t)\n'
    t += '\t)\n'
    t += '\t(embedded_fonts no)\n'
    t += ')\n'

    # Write
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{project_name}.kicad_sch")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(t)
    print(f"Generated root schematic: {output_path}")

    sheet_uuids = [(root_uuid, "Root")] + [(sh["uuid"], sh["name"]) for sh in sheet_items]
    return output_path, root_uuid, sheet_uuids


def generate_project_file(project_name, output_dir, sheet_uuids=None):
    """Generate a minimal .kicad_pro file.

    Args:
        project_name: Used for filenames
        output_dir:   Where to write the .kicad_pro
        sheet_uuids:  List of (uuid, name) from generate_root_schematic
    """
    project_data = {
        "meta": {"filename": f"{project_name}.kicad_pro", "version": 2},
        "schematic": {
            "annotate_start_num": 0,
            "bom_fmt_settings": {"field_delimiter": ",", "name": "CSV",
                                 "ref_delimiter": ",", "string_delimiter": "\""},
            "connection_grid_size": 50.0,
            "drawing": {},
            "page_layout_descr_file": ""
        },
        "sheets": [],
        "text_variables": {}
    }

    if sheet_uuids:
        for uid, name in sheet_uuids:
            project_data["sheets"].append([uid, name])

    output_path = os.path.join(output_dir, f"{project_name}.kicad_pro")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(project_data, f, indent=2)
    print(f"Generated project file: {output_path}")
    return output_path
