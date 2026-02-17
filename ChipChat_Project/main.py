import uuid
import kicad_api
import project_builder

def generate_sheet(symbol_name, reference, value, footprint_name, output_filename, lib_path=None):
    """
    Generates a complete .kicad_sch file for a single component.
    """
    print(f"--- Generating sheet: {output_filename} ---")
    page_center_x = 297 / 2
    page_center_y = 210 / 2
    sheet_uuid = str(uuid.uuid4())

    schematic_data = kicad_api.create_schematic_data(output_filename, sheet_uuid)

    lib_id = kicad_api.embed_symbol_from_file(
        schematic_data,
        symbol_name,
        library_path=lib_path
    )

    if lib_id:
        kicad_api.place_component(
            schematic_data=schematic_data,
            lib_id=lib_id,
            reference=reference,
            value=value,
            position=(page_center_x, page_center_y),
            footprint=footprint_name
        )

    kicad_api.save_schematic(schematic_data, output_filename)
    print(f"--- Finished sheet: {output_filename} ---\n")


def main():
    # --- Step 1: Build project.json from part numbers ---
    project = project_builder.build_project(
        project_name="ChipChat_Project",
        parts=[
            "USB_C_Receptacle_USB2.0_16P",
            "TPS628438DRL",
            "MCP2221A-I_SL",
            "BME280"
        ],
        description=(
            "USB-C powered BME280 sensor board. "
            "USB-C connector provides 5V power. "
            "TPS628438 buck converter steps 5V down to 3.3V. "
            "MCP2221A bridges USB to I2C. "
            "BME280 sensor communicates over I2C at 3.3V."
        )
    )

    # --- Step 2: Generate schematic sheets ---
    generate_sheet(
        symbol_name="BME280",
        reference="U1",
        value="BME280",
        footprint_name="Footprint_Library:BME280",
        output_filename="BME280_Sensor.kicad_sch"
    )

    generate_sheet(
        symbol_name="MCP2210-I_SO",
        reference="U1",
        value="MCP2210-I/SO",
        footprint_name="Footprint_Library:MCP2210-I_SO",
        output_filename="MCP2210_USB_TO_SPI.kicad_sch"
    )


if __name__ == "__main__":
    main()
