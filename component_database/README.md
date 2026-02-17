# Component Database

Master component library for ChipChat. Stores reusable component specs (pins, voltages, VIH/VIL, symbol/footprint references).

## Current Components

- **BME280** — Environmental sensor (humidity, pressure, temperature)
- **USB_C_Receptacle_USB2.0_16P** — USB Type-C connector
- **TPS628438DRL** — Buck converter (5V → 3.3V)
- **MCP2221A-I_SL** — USB to I2C/UART bridge

## Usage

Components are copied into project JSON files via `project_helper.create_project()`.
