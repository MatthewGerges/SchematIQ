"""
Schematic generator for KiCad - generates complete schematics from project.json
Uses Approach C: Hybrid (LLM reasoning + algorithmic layout)
"""

import json
import uuid
import os
import kicad_api
import project_builder

# Component positions for BME280_Sensor sheet (in mm, A4 page)
# Based on typical KiCad layout conventions
LAYOUT_BME280 = {
    "U3": {"x": 127.0, "y": 101.6, "angle": 0},  # Center of page
    "R5": {"x": 177.8, "y": 88.9, "angle": 90},   # Vertical, right of U3
    "R6": {"x": 177.8, "y": 114.3, "angle": 90}, # Vertical, right of U3
    "R9": {"x": 127.0, "y": 127.0, "angle": 0},  # Horizontal, below U3
    "C9": {"x": 190.5, "y": 88.9, "angle": 0},    # Horizontal, right
    "C10": {"x": 190.5, "y": 114.3, "angle": 0},  # Horizontal, right
    # Power symbols
    "+3.3V": {"x": 127.0, "y": 50.8, "angle": 0},  # Top center
    "GND_1": {"x": 88.9, "y": 127.0, "angle": 0},  # Left, below U3
    "GND_2": {"x": 165.1, "y": 127.0, "angle": 0}, # Right, below U3
    "GND_3": {"x": 190.5, "y": 127.0, "angle": 0},  # Far right
    # Hierarchical labels (left side)
    "I2C_SCL_BME": {"x": 50.8, "y": 88.9, "angle": 0, "shape": "output"},
    "I2C_SDA_BME": {"x": 50.8, "y": 114.3, "angle": 0, "shape": "bidirectional"},
    # Local labels
    "PP_3V3_OUT": {"x": 127.0, "y": 76.2, "angle": 0},
    "I2C_SCL_OR": {"x": 152.4, "y": 88.9, "angle": 0},
    "I2C_SDA_OR": {"x": 152.4, "y": 114.3, "angle": 0},
    "SDO_ADD": {"x": 127.0, "y": 127.0, "angle": 0},
}

# Pin positions relative to component center (approximate, in mm)
# These are estimates based on typical KiCad symbol pin spacing
PIN_OFFSETS = {
    "BME280": {
        "1": (0, -7.62),   # GND (bottom)
        "3": (-5.08, 0),   # SDI (left)
        "4": (-5.08, -2.54), # SCK (left)
        "5": (0, 7.62),    # SDO (top)
        "6": (5.08, -2.54), # VDDIO (right)
        "7": (0, 7.62),    # GND (top)
        "8": (5.08, 0),    # VDD (right)
    },
    "R": {
        "1": (-2.54, 0),   # Left pin
        "2": (2.54, 0),    # Right pin
    },
    "C": {
        "1": (-2.54, 0),   # Left pin
        "2": (2.54, 0),    # Right pin
    }
}


def _get_pin_position(component_ref, component_type, pin_num, layout):
    """Calculate absolute pin position based on component position and pin offset."""
    comp_pos = layout.get(component_ref, {})
    comp_x = comp_pos.get("x", 0)
    comp_y = comp_pos.get("y", 0)
    comp_angle = comp_pos.get("angle", 0)
    
    # Get pin offset
    if component_type == "BME280":
        offset = PIN_OFFSETS["BME280"].get(pin_num, (0, 0))
    elif component_type in ["R", "C"]:
        offset = PIN_OFFSETS[component_type].get(pin_num, (-2.54, 0))
    else:
        offset = (0, 0)
    
    # Apply rotation (simplified - only handles 0 and 90 degrees)
    if comp_angle == 90:
        offset = (-offset[1], offset[0])
    elif comp_angle == 270:
        offset = (offset[1], -offset[0])
    elif comp_angle == 180:
        offset = (-offset[0], -offset[1])
    
    return (comp_x + offset[0], comp_y + offset[1])


def _add_wire(schematic_data, x1, y1, x2, y2):
    """Add a wire segment to the schematic."""
    wire = {
        "type": "wire",
        "pts": [(x1, y1), (x2, y2)],
        "uuid": str(uuid.uuid4())
    }
    schematic_data["items"].append(wire)


def _add_label(schematic_data, text, position, net_name=None):
    """Add a local net label."""
    label = {
        "type": "label",
        "text": text,
        "at": position,
        "uuid": str(uuid.uuid4()),
        "net_name": net_name or text
    }
    schematic_data["items"].append(label)


def _add_hierarchical_label(schematic_data, text, position, shape="bidirectional"):
    """Add a hierarchical label."""
    label = {
        "type": "hierarchical_label",
        "text": text,
        "at": position,
        "shape": shape,
        "uuid": str(uuid.uuid4())
    }
    schematic_data["items"].append(label)


def _add_power_symbol(schematic_data, lib_id, position, value):
    """Add a power symbol (GND, +3.3V, etc.)."""
    power = {
        "type": "power_symbol",
        "lib_id": lib_id,
        "at": position,
        "value": value,
        "uuid": str(uuid.uuid4())
    }
    schematic_data["items"].append(power)


def _format_wire(wire):
    """Format a wire for KiCad output."""
    pts = wire["pts"]
    return f'\t(wire\n\t\t(pts\n\t\t\t(xy {pts[0][0]} {pts[0][1]}) (xy {pts[1][0]} {pts[1][1]})\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n\t\t(uuid "{wire["uuid"]}")\n\t)'


def _format_label(label):
    """Format a local label for KiCad output."""
    at = label["at"]
    return f'\t(label "{label["text"]}"\n\t\t(at {at[0]} {at[1]} 0)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t)\n\t\t(uuid "{label["uuid"]}")\n\t)'


def _format_hierarchical_label(label):
    """Format a hierarchical label for KiCad output."""
    at = label["at"]
    shape = label.get("shape", "bidirectional")
    return f'\t(hierarchical_label "{label["text"]}"\n\t\t(shape {shape})\n\t\t(at {at[0]} {at[1]} 0)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t)\n\t\t(uuid "{label["uuid"]}")\n\t)'


def _format_power_symbol(power):
    """Format a power symbol for KiCad output."""
    at = power["at"]
    lib_id = power["lib_id"]
    value = power["value"]
    ref = f"#PWR{hash(value) % 10000:04d}"
    
    return f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at {at[0]} {at[1]} 0)\n\t\t(unit 1)\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n\t\t(uuid "{power["uuid"]}")\n\t\t(property "Reference" "{ref}"\n\t\t\t(at {at[0]} {at[1] + 3.81} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n\t\t)\n\t\t(property "Value" "{value}"\n\t\t\t(at {at[0]} {at[1]} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t)\n\t\t)\n\t\t(property "Footprint" ""\n\t\t\t(at {at[0]} {at[1]} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n\t\t)\n\t\t(property "Datasheet" ""\n\t\t\t(at {at[0]} {at[1]} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n\t\t)\n\t\t(property "Description" "Power symbol creates a global label with name \\"{value}\\""\n\t\t\t(at {at[0]} {at[1]} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n\t\t)\n\t\t(pin "1"\n\t\t\t(uuid "{str(uuid.uuid4())}")\n\t\t)\n\t)'


def _generate_wires_for_net(schematic_data, net_name, connections, layout, project_data):
    """Generate wires connecting all components on a net."""
    # Group connections by component
    comp_pins = {}
    label_pos = None
    
    for conn in connections:
        ref = conn.get("ref")
        pin = conn.get("pin")
        sheet = conn.get("sheet")
        
        # Only process connections on this sheet
        if sheet and sheet != "BME280_Sensor":
            continue
        
        if not ref or not pin:
            continue
        
        # Get component type
        comp_type = None
        for comp in project_data.get("components", []):
            if comp["ref"] == ref:
                comp_type = comp.get("part", "")
                break
        if not comp_type:
            for passive in project_data.get("passives", []):
                if passive["ref"] == ref:
                    comp_type = passive.get("type", "")
                    break
        
        if not comp_type:
            continue
        
        # Calculate pin position
        pin_pos = _get_pin_position(ref, comp_type, pin, layout)
        
        if ref not in comp_pins:
            comp_pins[ref] = []
        comp_pins[ref].append({"pin": pin, "pos": pin_pos})
        
        # Check if there's a label position for this net
        if net_name in layout:
            label_info = layout[net_name]
            if isinstance(label_info, dict) and "x" in label_info:
                label_pos = (label_info["x"], label_info["y"])
    
    # Connect all pins on this net
    if len(comp_pins) < 2:
        # Only one component or no connections - connect to label if available
        if label_pos and comp_pins:
            for ref, pins in comp_pins.items():
                for pin_info in pins:
                    _add_wire(schematic_data, pin_info["pos"][0], pin_info["pos"][1],
                             label_pos[0], label_pos[1])
        return
    
    # Simple star topology: connect all pins to a central point
    # Find center point
    all_positions = []
    for pins in comp_pins.values():
        for pin_info in pins:
            all_positions.append(pin_info["pos"])
    
    if label_pos:
        center = label_pos
    else:
        # Calculate center
        center_x = sum(p[0] for p in all_positions) / len(all_positions)
        center_y = sum(p[1] for p in all_positions) / len(all_positions)
        center = (center_x, center_y)
    
    # Connect all pins to center
    for pins in comp_pins.values():
        for pin_info in pins:
            _add_wire(schematic_data, pin_info["pos"][0], pin_info["pos"][1],
                     center[0], center[1])


def generate_bme280_sensor_sheet(project_json_path, output_path):
    """
    Generate the BME280_Sensor schematic sheet from project.json.
    
    Args:
        project_json_path: Path to project.json file
        output_path: Path where to save the .kicad_sch file
    """
    # Load project data
    with open(project_json_path, 'r', encoding='utf-8') as f:
        project_data = json.load(f)
    
    # Create schematic data structure
    sheet_uuid = str(uuid.uuid4())
    schematic_data = kicad_api.create_schematic_data("BME280_Sensor", sheet_uuid)
    
    # Get component database for symbol paths
    db = project_builder._load_database()
    
    # Place BME280 (U3)
    bme280_info = None
    for comp in project_data.get("components", []):
        if comp["ref"] == "U3" and comp["sheet"] == "BME280_Sensor":
            bme280_info = comp
            break
    
    if not bme280_info:
        print("ERROR: U3 BME280 not found in project.json")
        return
    
    # Embed BME280 symbol
    part_name = bme280_info["part"]
    symbol_lib_id = kicad_api.embed_symbol_from_file(
        schematic_data,
        part_name,
        library_path=None
    )
    
    if not symbol_lib_id:
        print(f"ERROR: Could not load symbol for {part_name}")
        return
    
    # Place U3
    u3_pos = LAYOUT_BME280["U3"]
    footprint = db.get(part_name, {}).get("footprint", {}).get("name", "")
    kicad_api.place_component(
        schematic_data,
        symbol_lib_id,
        "U3",
        part_name,
        (u3_pos["x"], u3_pos["y"]),
        angle=u3_pos["angle"],
        footprint=footprint
    )
    
    # Place passive components
    passives_on_sheet = [p for p in project_data.get("passives", [])
                        if p.get("sheet") == "BME280_Sensor"]
    
    for passive in passives_on_sheet:
        ref = passive["ref"]
        ptype = passive["type"]
        value = passive["value"]
        
        # Determine symbol library ID
        if ptype == "R":
            lib_id = "Device:R"
        elif ptype == "C":
            lib_id = "Device:C"
        else:
            print(f"WARNING: Unknown passive type {ptype} for {ref}")
            continue
        
        # Device:R and Device:C are standard KiCad symbols, no need to embed
        # Place component directly
        pos = LAYOUT_BME280.get(ref, {"x": 0, "y": 0, "angle": 0})
        kicad_api.place_component(
            schematic_data,
            lib_id,
            ref,
            value,
            (pos["x"], pos["y"]),
            angle=pos["angle"]
        )
    
    # Add power symbols
    # +3.3V power symbol
    pwr_pos = LAYOUT_BME280["+3.3V"]
    _add_power_symbol(schematic_data, "power:+3.3V", (pwr_pos["x"], pwr_pos["y"]), "+3.3V")
    
    # GND symbols
    for gnd_key in ["GND_1", "GND_2", "GND_3"]:
        gnd_pos = LAYOUT_BME280[gnd_key]
        _add_power_symbol(schematic_data, "power:GND", (gnd_pos["x"], gnd_pos["y"]), "GND")
    
    # Add hierarchical labels
    for label_key in ["I2C_SCL_BME", "I2C_SDA_BME"]:
        label_info = LAYOUT_BME280[label_key]
        _add_hierarchical_label(
            schematic_data,
            label_key,
            (label_info["x"], label_info["y"]),
            shape=label_info.get("shape", "bidirectional")
        )
    
    # Add local labels
    for label_key in ["PP_3V3_OUT", "I2C_SCL_OR", "I2C_SDA_OR", "SDO_ADD"]:
        label_info = LAYOUT_BME280[label_key]
        _add_label(
            schematic_data,
            label_key,
            (label_info["x"], label_info["y"]),
            net_name=label_key
        )
    
    # Generate wires for each net
    # Build a map of ref -> sheet for quick lookup
    ref_to_sheet = {}
    for comp in project_data.get("components", []):
        ref_to_sheet[comp["ref"]] = comp.get("sheet")
    for passive in project_data.get("passives", []):
        ref_to_sheet[passive["ref"]] = passive.get("sheet")
    
    for net in project_data.get("nets", []):
        # Filter connections to this sheet
        sheet_connections = []
        for conn in net.get("connections", []):
            ref = conn.get("ref")
            conn_sheet = conn.get("sheet")
            
            # If sheet is specified in connection, use it
            if conn_sheet == "BME280_Sensor":
                sheet_connections.append(conn)
            # Otherwise, check if component is on this sheet
            elif ref in ref_to_sheet and ref_to_sheet[ref] == "BME280_Sensor":
                # Create a copy with sheet info
                conn_copy = conn.copy()
                conn_copy["sheet"] = "BME280_Sensor"
                sheet_connections.append(conn_copy)
        
        if sheet_connections:
            _generate_wires_for_net(
                schematic_data,
                net["name"],
                sheet_connections,
                LAYOUT_BME280,
                project_data
            )
    
    # Generate and save schematic
    _save_schematic_with_extensions(schematic_data, output_path)
    print(f"\n✓ BME280_Sensor schematic generated: {output_path}")


def _save_schematic_with_extensions(schematic_data, file_path):
    """Save schematic with wires, labels, and power symbols."""
    text = f'(kicad_sch (version {schematic_data["version"]}) (generator "{schematic_data["generator"]}")\n'
    text += f'\t(uuid "{schematic_data["uuid"]}")\n'
    text += f'\t(paper "{schematic_data["paper"]}")\n\n'
    
    # Embedded symbols
    if schematic_data["lib_symbols"]:
        text += "\t(lib_symbols\n"
        for symbol_def in schematic_data["lib_symbols"]:
            text += f"\t{symbol_def}\n"
        text += "\t)\n\n"
    
    # Components and other items
    for item in schematic_data["items"]:
        if item["type"] == "symbol":
            text += "\t(symbol\n"
            text += f'\t\t(lib_id "{item["lib_id"]}")\n'
            text += f'\t\t(at {item["at"][0]} {item["at"][1]} {item["at"][2]})\n'
            text += f'\t\t(uuid "{item["uuid"]}")'
            # Format properties manually (since _format_properties is private)
            prop_text = ""
            ref_at_y = item["at"][1] + 2.54 
            val_at_y = item["at"][1] - 2.54
            
            if "Reference" in item["properties"]:
                prop_text += f'\n\t\t(property "Reference" "{item["properties"]["Reference"]}" (at {item["at"][0]} {ref_at_y} 0) (effects (font (size 1.27 1.27))))'
            if "Value" in item["properties"]:
                prop_text += f'\n\t\t(property "Value" "{item["properties"]["Value"]}" (at {item["at"][0]} {val_at_y} 0) (effects (font (size 1.27 1.27))))'
            
            footprint = item["properties"].get("Footprint", "")
            prop_text += f'\n\t\t(property "Footprint" "{footprint}" (at {item["at"][0]} {item["at"][1]} 0) (effects (font (size 1.27 1.27)) (hide yes)))'
            prop_text += f'\n\t\t(property "Datasheet" "" (at {item["at"][0]} {item["at"][1]} 0) (effects (font (size 1.27 1.27)) (hide yes)))'
            text += prop_text
            text += "\n\t)\n"
        elif item["type"] == "wire":
            text += _format_wire(item) + "\n"
        elif item["type"] == "label":
            text += _format_label(item) + "\n"
        elif item["type"] == "hierarchical_label":
            text += _format_hierarchical_label(item) + "\n"
        elif item["type"] == "power_symbol":
            text += _format_power_symbol(item) + "\n"
    
    text += ")\n"
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Schematic saved to {file_path}")
