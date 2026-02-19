"""Functions to generate KiCad project files (.kicad_pro and .kicad_sch root)."""
import json
import uuid
import os


def generate_project_file(project_name, root_schematic_path, output_dir, sheet_uuids=None):
    """
    Generates a .kicad_pro file for the project.
    
    Args:
        project_name: Name of the project
        root_schematic_path: Path to the root schematic file (relative to output_dir)
        output_dir: Directory where the .kicad_pro file will be saved
        sheet_uuids: List of tuples (uuid, sheet_name) for the sheets list
    """
    # Try to read existing project file as template, or create minimal one
    existing_proj_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(output_dir))), 
                                      f"{project_name}.kicad_pro")
    if os.path.exists(existing_proj_path):
        with open(existing_proj_path, 'r', encoding='utf-8') as f:
            project_data = json.load(f)
        # Update the schematic path
        if "project" in project_data:
            project_data["project"]["schematic"] = root_schematic_path
        # Update sheets list if provided
        if sheet_uuids and "sheets" in project_data:
            project_data["sheets"] = sheet_uuids
    else:
        # Create minimal project data
        project_data = {
        "board": {
            "3dviewports": [],
            "design_settings": {
                "defaults": {
                    "apply_defaults_to_fp_fields": False,
                    "apply_defaults_to_fp_shapes": False,
                    "apply_defaults_to_fp_text": False,
                    "board_outline_line_width": 0.05,
                    "copper_line_width": 0.2,
                    "copper_text_italic": False,
                    "copper_text_size_h": 1.5,
                    "copper_text_size_v": 1.5,
                    "copper_text_thickness": 0.3,
                    "copper_text_upright": False,
                    "courtyard_line_width": 0.05,
                    "dimension_precision": 4,
                    "dimension_units": 3,
                    "dimensions": {
                        "arrow_length": 1270000,
                        "extension_offset": 500000,
                        "keep_text_aligned": True,
                        "suppress_zeroes": True,
                        "text_position": 0,
                        "units_format": 0
                    },
                    "fab_line_width": 0.1,
                    "fab_text_italic": False,
                    "fab_text_size_h": 1.0,
                    "fab_text_size_v": 1.0,
                    "fab_text_thickness": 0.15,
                    "fab_text_upright": False,
                    "other_line_width": 0.1,
                    "other_text_italic": False,
                    "other_text_size_h": 1.0,
                    "other_text_size_v": 1.0,
                    "other_text_thickness": 0.15,
                    "other_text_upright": False,
                    "pads": {
                        "drill": 0.8,
                        "height": 1.27,
                        "width": 2.54
                    },
                    "silk_line_width": 0.1,
                    "silk_text_italic": False,
                    "silk_text_size_h": 1.0,
                    "silk_text_size_v": 1.0,
                    "silk_text_thickness": 0.1,
                    "silk_text_upright": False,
                    "zones": {
                        "min_clearance": 0.5
                    }
                },
                "diff_pair_dimensions": [],
                "drc_exclusions": [],
                "meta": {
                    "version": 2
                },
                "rule_severities": {
                    "annular_width": "error",
                    "clearance": "error",
                    "connection_width": "error",
                    "copper_edge_clearance": "error",
                    "copper_sliver": "error",
                    "courtyards_overlap": "error",
                    "diff_pair_gap_out_of_range": "error",
                    "diff_pair_uncoupled_length_too_long": "error",
                    "drill_out_of_range": "error",
                    "duplicate_footprints": "error",
                    "extra_footprint": "error",
                    "footprint": "error",
                    "footprint_type_mismatch": "error",
                    "hole_clearance": "error",
                    "hole_near_hole": "error",
                    "invalid_outline": "error",
                    "length_out_of_range": "error",
                    "malformed_courtyard": "error",
                    "microvia_drill_out_of_range": "error",
                    "missing_courtyard": "warning",
                    "missing_footprint": "error",
                    "net_conflict": "error",
                    "npth_inside_courtyard": "error",
                    "padstack": "error",
                    "pth_inside_courtyard": "error",
                    "shorting_items": "error",
                    "silk_edge_clearance": "error",
                    "silk_over_copper": "warning",
                    "silk_over_pads": "warning",
                    "silk_sliver": "error",
                    "solder_mask_bridge": "error",
                    "starved_thermal": "error",
                    "text_height": "warning",
                    "text_thickness": "warning",
                    "through_hole_pad_without_hole": "error",
                    "too_many_vias": "error",
                    "track_dangling": "warning",
                    "track_dc_error": "error",
                    "track_width": "error",
                    "tracks_crossing": "error",
                    "unconnected_items": "error",
                    "unresolved_variable": "error",
                    "via_annular_width": "error",
                    "via_dangling": "warning",
                    "zones_intersect": "error"
                },
                "rule_severities_metadata": {},
                "rules": {
                    "max_error": 0.0,
                    "min_clearance": 0.0,
                    "min_connection": 0.0,
                    "min_copper_edge_clearance": 0.0,
                    "min_hole_clearance": 0.0,
                    "min_hole_to_hole": 0.0,
                    "min_microvia_diameter": 0.0,
                    "min_microvia_drill": 0.0,
                    "min_resolved_spokes": 0,
                    "min_silk_clearance": 0.0,
                    "min_text_height": 0.0,
                    "min_text_thickness": 0.0,
                    "min_track_width": 0.0,
                    "min_via_annular_width": 0.0,
                    "min_via_diameter": 0.0,
                    "min_via_drill": 0.0,
                    "solder_mask_clearance": 0.0,
                    "solder_mask_min_width": 0.0,
                    "solder_mask_to_copper_clearance": 0.0
                },
                "solder_mask_expansion": 0.0,
                "solder_mask_min_clearance": 0.0,
                "solder_mask_to_copper_clearance": 0.0
            },
            "stackup": {
                "layers": []
            }
        },
        "net_settings": {
            "classes": [
                {
                    "bus_width": 12.0,
                    "clearance": 0.2,
                    "diff_pair_gap": 0.25,
                    "diff_pair_via_gap": 0.25,
                    "diff_pair_width": 0.2,
                    "line_style": 0,
                    "microvia_diameter": 0.3,
                    "microvia_drill": 0.1,
                    "name": "Default",
                    "pcb_color": "rgba(0, 0, 0, 0.000)",
                    "schematic_color": "rgba(0, 0, 0, 0.000)",
                    "track_width": 0.25,
                    "via_diameter": 0.8,
                    "via_drill": 0.4,
                    "wire_width": 6.0
                }
            ],
            "meta": {
                "version": 3
            }
        },
        "schematic": root_schematic_path,
        "schematic": {
            "annotate_start_num": 0,
            "bom_export_filename": "${PROJECTNAME}.csv",
            "bom_fmt_presets": [],
            "bom_fmt_settings": {
                "field_delimiter": ",",
                "keep_line_breaks": False,
                "keep_tabs": False,
                "name": "CSV",
                "ref_delimiter": ",",
                "ref_range_delimiter": "",
                "string_delimiter": "\""
            },
            "bom_presets": [],
            "bom_settings": {
                "exclude_dnp": False,
                "fields_ordered": [
                    {
                        "group_by": False,
                        "label": "Reference",
                        "name": "Reference",
                        "show": True
                    },
                    {
                        "group_by": False,
                        "label": "Qty",
                        "name": "${QUANTITY}",
                        "show": True
                    },
                    {
                        "group_by": True,
                        "label": "Value",
                        "name": "Value",
                        "show": True
                    },
                    {
                        "group_by": True,
                        "label": "Footprint",
                        "name": "Footprint",
                        "show": True
                    }
                ],
                "filter_string": "",
                "group_symbols": True,
                "include_excluded_from_bom": True,
                "name": "Default Editing",
                "sort_asc": True,
                "sort_field": "Reference"
            },
            "connection_grid_size": 50.0,
            "drawing": {},
            "page_layout_descr_file": ""
        },
        "text_variables": {}
    }
    
    # Add project section with schematic path
    project_data["project"] = {
        "name": project_name,
        "schematic": root_schematic_path,
        "stackup": {
            "layers": []
        }
    }
    
    # Add sheets list (will be populated when we know the sheet UUIDs)
    project_data["sheets"] = []
    
    output_path = os.path.join(output_dir, f"{project_name}.kicad_pro")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(project_data, f, indent=2)
    
    print(f"Generated project file: {output_path}")
    return output_path


def generate_root_schematic(project_name, sheet_files, output_dir):
    """
    Generates the root .kicad_sch file that references sub-sheets.
    
    Args:
        project_name: Name of the project
        sheet_files: List of tuples (sheet_name, sheet_file_path relative to output_dir)
        output_dir: Directory where the .kicad_sch file will be saved
    """
    import uuid as uuid_module
    
    sheet_uuid = str(uuid_module.uuid4())
    root_uuid = str(uuid_module.uuid4())
    
    # Generate sheet instances
    sheet_instances = []
    y_pos = 30.48
    for i, (sheet_name, sheet_file) in enumerate(sheet_files):
        sheet_instances.append({
            "uuid": str(uuid_module.uuid4()),
            "at": (30.48, y_pos + i * 30.48),
            "size": (40.64, 20.32),
            "sheetname": sheet_name,
            "sheetfile": sheet_file
        })
    
    # Generate the root schematic content
    content = f'''(kicad_sch
	(version 20250114)
	(generator "eeschema")
	(generator_version "9.0")
	(uuid "{root_uuid}")
	(paper "A4")
	(lib_symbols)
'''
    
    # Add sheet definitions
    for sheet in sheet_instances:
        content += f'''	(sheet
		(at {sheet["at"][0]} {sheet["at"][1]})
		(size {sheet["size"][0]} {sheet["size"][1]})
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(dnp no)
		(stroke
			(width 0)
			(type solid)
		)
		(fill
			(color 0 0 0 0.0000)
		)
		(uuid "{sheet["uuid"]}")
		(property "Sheetname" "{sheet["sheetname"]}"
			(at {sheet["at"][0]} {sheet["at"][1] - 0.68} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(justify left bottom)
			)
		)
		(property "Sheetfile" "{sheet["sheetfile"]}"
			(at {sheet["at"][0]} {sheet["at"][1] + 20.52} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(justify left top)
			)
		)
	)
'''
    
    # Add sheet instances
    content += '''	(sheet_instances
		(path "/"
			(page "1")
		)
	)
	(embedded_fonts no)
)
'''
    
    output_path = os.path.join(output_dir, f"{project_name}.kicad_sch")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"Generated root schematic: {output_path}")
    
    # Return root UUID and sheet UUIDs for .kicad_pro file
    sheet_uuids = [(root_uuid, "Root")] + [(s["uuid"], s["sheetname"]) for s in sheet_instances]
    return output_path, sheet_uuids
