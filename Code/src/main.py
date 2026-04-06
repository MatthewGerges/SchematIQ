import uuid
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import kicad_api
from src.lib import project_builder
from src.lib import project_generator

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
        project_name="SchematIQ_Demo",
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
    # Output to generated/ folder
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    generated_dir = os.path.join(base_dir, "generated")
    os.makedirs(generated_dir, exist_ok=True)
    
    generate_sheet(
        symbol_name="BME280",
        reference="U1",
        value="BME280",
        footprint_name="Footprint_Library:BME280",
        output_filename=os.path.join(generated_dir, "BME280_Sensor.kicad_sch")
    )

    generate_sheet(
        symbol_name="MCP2210-I_SO",
        reference="U1",
        value="MCP2210-I/SO",
        footprint_name="Footprint_Library:MCP2210-I_SO",
        output_filename=os.path.join(generated_dir, "MCP2210_USB_TO_SPI.kicad_sch")
    )
    
    # --- Step 3: Generate root project files in generated/ folder ---
    project_name = "SchematIQ_Demo"
    root_schematic, sheet_uuids = project_generator.generate_root_schematic(
        project_name=project_name,
        sheet_files=[
            ("BME280_Sensor", "BME280_Sensor.kicad_sch"),
            ("MCP2210_USB_TO_SPI", "MCP2210_USB_TO_SPI.kicad_sch")
        ],
        output_dir=generated_dir
    )
    
    project_generator.generate_project_file(
        project_name=project_name,
        root_schematic_path=f"{project_name}.kicad_sch",
        output_dir=generated_dir,
        sheet_uuids=sheet_uuids
    )


if __name__ == "__main__":
    main()
