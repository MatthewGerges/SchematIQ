import uuid
import kicad_api
import project_helper


def generate_sheet(symbol_name, reference, value, footprint_name, output_filename, lib_path=None):
    """
    Generates a complete .kicad_sch file for a single component.

    Args:
        symbol_name (str): The name of the symbol (and .kicad_sym file).
        reference (str): The component reference (e.g., "U1").
        value (str): The component value.
        footprint_name (str): The footprint to be linked (e.g., "BME280.kicad_mod").
        output_filename (str): The name of the .kicad_sch file to generate.
        lib_path (str, optional): Path to the symbol library. Defaults to None.
    """
    print(f"--- Generating sheet: {output_filename} ---")
    # Page layout constants
    page_center_x = 297 / 2
    page_center_y = 210 / 2
    sheet_uuid = str(uuid.uuid4())

    # 1. Create the basic data structure for the sheet.
    schematic_data = kicad_api.create_schematic_data(output_filename, sheet_uuid)

    # 2. Embed the symbol from its .kicad_sym file.
    lib_id = kicad_api.embed_symbol_from_file(
        schematic_data,
        symbol_name,
        library_path=lib_path
    )

    # 3. If the symbol was found and embedded, place it with the footprint.
    if lib_id:
        kicad_api.place_component(
            schematic_data=schematic_data,
            lib_id=lib_id,
            reference=reference,
            value=value,
            position=(page_center_x, page_center_y),
            footprint=footprint_name
        )

    # 4. Save the generated schematic to its file.
    file_path = f"ChipChat_Project/{output_filename}"
    kicad_api.save_schematic(schematic_data, file_path)
    print(f"--- Finished sheet: {output_filename} ---\n")


def main():
    """
    Main function to generate the project.
    Step 1: Copy components from the master database into project.json
    Step 2 (future): Add connections/nets
    Step 3 (future): Generate schematic sheets from project.json
    """

    # --- Step 1: Build project.json from master database ---
    print("=== Step 1: Building project.json from master database ===\n")
    project_helper.list_available_parts()
    print()

    project = project_helper.create_project(
        project_name="ChipChat_Project",
        part_names=[
            "USB_C_Receptacle_USB2.0_16P",
            "TPS628438DRL",
            "MCP2221A-I_SL",
            "BME280"
        ]
    )

    # Print summary of what was copied
    print("\n=== Project summary ===")
    for comp in project["components"]:
        pin_count = len(comp.get("pins", []))
        print(f"  {comp['name']} - {comp['type']} - {pin_count} pins")


if __name__ == "__main__":
    main()
