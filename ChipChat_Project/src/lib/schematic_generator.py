"""
Schematic generator for KiCad - generates complete schematics from project.json
Uses Approach C: Hybrid (LLM reasoning + algorithmic layout)
"""

import json
import uuid
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.lib import kicad_api
from src.lib import project_builder

# Improved layout - use more of the page, better spacing
# A4 page: 297mm x 210mm
# Use larger spacing to avoid wire crossovers
GRID_X_START = 50.8  # Start 2 inches from left
GRID_Y_START = 50.8  # Start 2 inches from top
GRID_SPACING_X = 50.8  # 2 inch horizontal spacing (more room)
GRID_SPACING_Y = 38.1  # 1.5 inch vertical spacing
WIRE_LENGTH = 7.62  # 0.3 inch wire stub for labels (longer for clarity)
PAGE_WIDTH = 297.0  # A4 width in mm
PAGE_HEIGHT = 210.0  # A4 height in mm

# Component order: left-to-right, top-to-bottom
COMPONENT_ORDER = [
    "U3",   # BME280 (main component, top-left)
    "R5",   # I2C SCL pullup
    "R6",   # I2C SDA pullup
    "R9",   # Address select resistor
    "C9",   # VDD decoupling
    "C10",  # VDDIO decoupling
]

# Pin positions relative to component center (in mm)
# Standard KiCad pin spacing: 2.54mm (0.1 inch) for most components
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
        "1": (-2.54, 0),   # Left pin (horizontal resistor)
        "2": (2.54, 0),    # Right pin
    },
    "C": {
        "1": (-2.54, 0),   # Left pin (horizontal capacitor)
        "2": (2.54, 0),    # Right pin
    }
}


def _embed_device_symbol(schematic_data, symbol_type):
    """Embed a standard Device symbol (R or C) into the schematic."""
    import uuid as uuid_module
    
    # Generate proper UUIDs for pins
    pin1_uuid = str(uuid_module.uuid4())
    pin2_uuid = str(uuid_module.uuid4())
    
    if symbol_type == "R":
        symbol_def = f'''(symbol "Device:R"
	(pin_numbers
		(hide yes)
	)
	(pin_names
		(offset 0)
	)
	(exclude_from_sim no)
	(in_bom yes)
	(on_board yes)
	(property "Reference" "R"
		(at 2.032 0 90)
		(effects
			(font
				(size 1.27 1.27)
			)
		)
	)
	(property "Value" "R"
		(at 0 0 90)
		(effects
			(font
				(size 1.27 1.27)
			)
		)
	)
	(property "Footprint" ""
		(at -1.778 0 90)
		(effects
			(font
				(size 1.27 1.27)
			)
			(hide yes)
		)
	)
	(property "Datasheet" "~"
		(at 0 0 0)
		(effects
			(font
				(size 1.27 1.27)
			)
			(hide yes)
		)
	)
	(property "Description" "Resistor"
		(at 0 0 0)
		(effects
			(font
				(size 1.27 1.27)
			)
			(hide yes)
		)
	)
	(symbol "R_0_1"
		(rectangle
			(start -1.016 -2.54)
			(end 1.016 2.54)
			(stroke
				(width 0.254)
				(type default)
			)
			(fill
				(type none)
			)
		)
	)
	(symbol "R_1_1"
		(pin passive line
			(at 0 3.81 270)
			(length 1.27)
			(name "~"
				(effects
					(font
						(size 1.27 1.27)
					)
				)
			)
			(number "1"
				(effects
					(font
						(size 1.27 1.27)
					)
				)
			)
			(uuid "{pin1_uuid}")
		)
		(pin passive line
			(at 0 -3.81 90)
			(length 1.27)
			(name "~"
				(effects
					(font
						(size 1.27 1.27)
					)
				)
			)
			(number "2"
				(effects
					(font
						(size 1.27 1.27)
					)
				)
			)
			(uuid "{pin2_uuid}")
		)
	)
)'''
    elif symbol_type == "C":
        pin3_uuid = str(uuid_module.uuid4())
        pin4_uuid = str(uuid_module.uuid4())
        symbol_def = f'''(symbol "Device:C"
	(pin_numbers
		(hide yes)
	)
	(pin_names
		(offset 0.254)
	)
	(exclude_from_sim no)
	(in_bom yes)
	(on_board yes)
	(property "Reference" "C"
		(at 0.635 2.54 0)
		(effects
			(font
				(size 1.27 1.27)
			)
			(justify left)
		)
	)
	(property "Value" "C"
		(at 0.635 -2.54 0)
		(effects
			(font
				(size 1.27 1.27)
			)
			(justify left)
		)
	)
	(property "Footprint" ""
		(at 0.9652 -3.81 0)
		(effects
			(font
				(size 1.27 1.27)
			)
			(hide yes)
		)
	)
	(property "Datasheet" "~"
		(at 0 0 0)
		(effects
			(font
				(size 1.27 1.27)
			)
			(hide yes)
		)
	)
	(property "Description" "Unpolarized capacitor"
		(at 0 0 0)
		(effects
			(font
				(size 1.27 1.27)
			)
			(hide yes)
		)
	)
	(symbol "C_0_1"
		(polyline
			(pts
				(xy -2.032 0.762) (xy 2.032 0.762)
			)
			(stroke
				(width 0.508)
				(type default)
			)
			(fill
				(type none)
			)
		)
		(polyline
			(pts
				(xy -2.032 -0.762) (xy 2.032 -0.762)
			)
			(stroke
				(width 0.508)
				(type default)
			)
			(fill
				(type none)
			)
		)
	)
	(symbol "C_1_1"
		(pin passive line
			(at 0 3.81 270)
			(length 1.27)
			(name "~"
				(effects
					(font
						(size 1.27 1.27)
					)
				)
			)
			(number "1"
				(effects
					(font
						(size 1.27 1.27)
					)
				)
			)
			(uuid "{pin3_uuid}")
		)
		(pin passive line
			(at 0 -3.81 90)
			(length 1.27)
			(name "~"
				(effects
					(font
						(size 1.27 1.27)
					)
				)
			)
			(number "2"
				(effects
					(font
						(size 1.27 1.27)
					)
				)
			)
			(uuid "{pin4_uuid}")
		)
	)
)'''
    else:
        return
    
    # Add to lib_symbols
    schematic_data["lib_symbols"].append(symbol_def)
    print(f"Embedded Device:{symbol_type} symbol")


def _get_component_position(index):
    """Calculate component position based on grid index (left-to-right, top-to-bottom)."""
    # 3 columns layout for better use of page width
    col = index % 3
    row = index // 3
    
    x = GRID_X_START + col * GRID_SPACING_X
    y = GRID_Y_START + row * GRID_SPACING_Y
    
    return {"x": x, "y": y, "angle": 0}


def _get_pin_position(component_ref, component_type, pin_num, component_pos):
    """Calculate absolute pin position based on component position and pin offset."""
    comp_x = component_pos["x"]
    comp_y = component_pos["y"]
    comp_angle = component_pos.get("angle", 0)
    
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


def _generate_wires_for_net(schematic_data, net_name, connections, component_positions, project_data):
    """Generate wires connecting all components on a net with labels."""
    # Group connections by component
    comp_pins = {}
    
    for conn in connections:
        ref = conn.get("ref")
        pin = conn.get("pin")
        
        if not ref or not pin:
            continue
        
        # Get component type and position
        comp_type = None
        comp_pos = None
        
        for comp in project_data.get("components", []):
            if comp["ref"] == ref:
                comp_type = comp.get("part", "")
                comp_pos = component_positions.get(ref)
                break
        if not comp_type:
            for passive in project_data.get("passives", []):
                if passive["ref"] == ref:
                    comp_type = passive.get("type", "")
                    comp_pos = component_positions.get(ref)
                    break
        
        if not comp_type or not comp_pos:
            continue
        
        # Calculate pin position
        pin_pos = _get_pin_position(ref, comp_type, pin, comp_pos)
        
        if ref not in comp_pins:
            comp_pins[ref] = []
        comp_pins[ref].append({"pin": pin, "pos": pin_pos})
    
    if not comp_pins:
        return
    
    # Improved routing: avoid crossovers by routing horizontally first, then vertically
    # Collect all pin positions
    all_pin_positions = []
    pin_to_ref = {}
    for ref, pins in comp_pins.items():
        for pin_info in pins:
            pos = pin_info["pos"]
            all_pin_positions.append(pos)
            pin_to_ref[pos] = ref
    
    if not all_pin_positions:
        return
    
    # Sort pins by Y, then X to route top-to-bottom, left-to-right
    all_pin_positions.sort(key=lambda p: (p[1], p[0]))
    
    # Find routing column (rightmost pin + spacing)
    max_x = max(p[0] for p in all_pin_positions)
    route_x = max_x + WIRE_LENGTH + 5.08  # Route column
    
    # Route each pin to the routing column, then connect vertically
    wire_stubs = []
    for pin_x, pin_y in all_pin_positions:
        # Horizontal stub from pin
        stub_end_x = pin_x + WIRE_LENGTH
        stub_end_y = pin_y
        _add_wire(schematic_data, pin_x, pin_y, stub_end_x, stub_end_y)
        
        # Horizontal to routing column
        _add_wire(schematic_data, stub_end_x, stub_end_y, route_x, stub_end_y)
        wire_stubs.append((route_x, stub_end_y))
    
    # Connect all stubs vertically in routing column
    if len(wire_stubs) > 1:
        wire_stubs.sort(key=lambda p: p[1])  # Sort by Y
        for i in range(len(wire_stubs) - 1):
            x1, y1 = wire_stubs[i]
            x2, y2 = wire_stubs[i + 1]
            _add_wire(schematic_data, x1, y1, x2, y2)
    
    # Place label at top of routing column
    label_y = min(p[1] for p in all_pin_positions) - 5.08
    label_x = route_x
    _add_label(schematic_data, net_name, (label_x, label_y), net_name)


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
    # Go up from src/lib/ -> src/ -> ChipChat_Project/ -> parent -> component_database/
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    COMPONENT_DB_PATH = os.path.join(BASE_DIR, "component_database", "components.json")
    with open(COMPONENT_DB_PATH, 'r', encoding='utf-8') as f:
        db = json.load(f)
    
    # Track component positions for wire generation
    component_positions = {}
    
    # Place BME280 (U3) - first component
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
    
    # Place U3 at position 0 (top-left)
    u3_pos = _get_component_position(0)
    component_positions["U3"] = u3_pos
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
    
    # Place passive components in order
    passives_on_sheet = [p for p in project_data.get("passives", [])
                        if p.get("sheet") == "BME280_Sensor"]
    
    # Sort passives by reference to match COMPONENT_ORDER (only include those in order)
    passives_on_sheet = [p for p in passives_on_sheet if p["ref"] in COMPONENT_ORDER]
    passives_on_sheet.sort(key=lambda p: COMPONENT_ORDER.index(p["ref"]))
    
    passive_index = 1  # Start after U3
    for passive in passives_on_sheet:
        ref = passive["ref"]
        ptype = passive["type"]
        value = passive["value"]
        
        # Determine symbol library ID and embed if needed
        if ptype == "R":
            lib_id = "Device:R"
            # Embed Device:R symbol if not already embedded
            if not any("Device:R" in str(s) for s in schematic_data["lib_symbols"]):
                _embed_device_symbol(schematic_data, "R")
        elif ptype == "C":
            lib_id = "Device:C"
            # Embed Device:C symbol if not already embedded
            if not any("Device:C" in str(s) for s in schematic_data["lib_symbols"]):
                _embed_device_symbol(schematic_data, "C")
        else:
            print(f"WARNING: Unknown passive type {ptype} for {ref}")
            continue
        
        # Place component at grid position
        pos = _get_component_position(passive_index)
        component_positions[ref] = pos
        kicad_api.place_component(
            schematic_data,
            lib_id,
            ref,
            value,
            (pos["x"], pos["y"]),
            angle=pos["angle"]
        )
        passive_index += 1
    
    # Add hierarchical labels on left side
    hier_y_start = GRID_Y_START
    _add_hierarchical_label(
        schematic_data,
        "I2C_SCL_BME",
        (GRID_X_START - 12.7, hier_y_start),
        shape="output"
    )
    _add_hierarchical_label(
        schematic_data,
        "I2C_SDA_BME",
        (GRID_X_START - 12.7, hier_y_start + GRID_SPACING_Y),
        shape="bidirectional"
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
                component_positions,
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
