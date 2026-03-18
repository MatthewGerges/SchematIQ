export default () => (
  <board routingDisabled>
    <net name="VDD" isForPower />
    <net name="GND" isGround />

    <subcircuit name="MCU_PAGE">
      <chip
        name="U1"
        manufacturerPartNumber="NRF54L15-QFAA-R"
        footprint="qfn32"
        schX={0}
        schY={0}
        schWidth={10}
        pinLabels={{
          pin1: "VDD1",
          pin2: "GND1",
          pin3: "VDD2",
          pin4: "GND2",
          pin5: "VDD3",
          pin6: "GND3",
          pin7: "VDD4",
          pin8: "GND4",
          pin9: "SWDIO",
          pin10: "SWDCLK",
          pin11: "RESET",
          pin12: "HFXO_IN",
          pin13: "HFXO_OUT",
          pin14: "LFXO_IN",
          pin15: "LFXO_OUT"
        }}
        schPinArrangement={{
          leftSide: {
            direction: "top-to-bottom",
            pins: ["SWDIO", "SWDCLK", "RESET", "HFXO_IN", "HFXO_OUT", "LFXO_IN", "LFXO_OUT"]
          },
          rightSide: {
            direction: "top-to-bottom",
            pins: ["VDD1", "GND1", "VDD2", "GND2", "VDD3", "GND3", "VDD4", "GND4"]
          }
        }}
      />

      <capacitor name="C1" footprint="0402" capacitance="100nF" schX={8} schY={3.5} />
      <capacitor name="C2" footprint="0402" capacitance="100nF" schX={8} schY={2.5} />
      <capacitor name="C3" footprint="0402" capacitance="100nF" schX={8} schY={1.5} />
      <capacitor name="C4" footprint="0402" capacitance="100nF" schX={8} schY={0.5} />
      <capacitor name="CBULK" footprint="0402" capacitance="4.7uF" schX={8} schY={-0.5} />

      <trace from=".C1 > .pin1" to="net.VDD" />
      <trace from=".C1 > .pin2" to="net.GND" />
      <trace from=".C2 > .pin1" to="net.VDD" />
      <trace from=".C2 > .pin2" to="net.GND" />
      <trace from=".C3 > .pin1" to="net.VDD" />
      <trace from=".C3 > .pin2" to="net.GND" />
      <trace from=".C4 > .pin1" to="net.VDD" />
      <trace from=".C4 > .pin2" to="net.GND" />
      <trace from=".CBULK > .pin1" to="net.VDD" />
      <trace from=".CBULK > .pin2" to="net.GND" />

      <trace from=".U1 > .VDD1" to="net.VDD" />
      <trace from=".U1 > .VDD2" to="net.VDD" />
      <trace from=".U1 > .VDD3" to="net.VDD" />
      <trace from=".U1 > .VDD4" to="net.VDD" />
      <trace from=".U1 > .GND1" to="net.GND" />
      <trace from=".U1 > .GND2" to="net.GND" />
      <trace from=".U1 > .GND3" to="net.GND" />
      <trace from=".U1 > .GND4" to="net.GND" />

      <crystal name="HFXO" frequency="32MHz" loadCapacitance="12pF" schX={-14} schY={5.5} />
      <capacitor name="C_HFXO1" footprint="0402" capacitance="12pF" schX={-9} schY={5.8} />
      <capacitor name="C_HFXO2" footprint="0402" capacitance="12pF" schX={-9} schY={5.2} />
      <trace from=".U1 > .HFXO_IN" to=".HFXO > .pin1" />
      <trace from=".U1 > .HFXO_OUT" to=".HFXO > .pin2" />
      <trace from=".HFXO > .pin1" to=".C_HFXO1 > .pin1" />
      <trace from=".C_HFXO1 > .pin2" to="net.GND" />
      <trace from=".HFXO > .pin2" to=".C_HFXO2 > .pin1" />
      <trace from=".C_HFXO2 > .pin2" to="net.GND" />

      <crystal name="LFXO" frequency="32.768kHz" loadCapacitance="12.5pF" schX={-14} schY={-5.5} />
      <capacitor name="C_LFXO1" footprint="0402" capacitance="12pF" schX={-9} schY={-5.2} />
      <capacitor name="C_LFXO2" footprint="0402" capacitance="12pF" schX={-9} schY={-5.8} />
      <trace from=".U1 > .LFXO_IN" to=".LFXO > .pin1" />
      <trace from=".U1 > .LFXO_OUT" to=".LFXO > .pin2" />
      <trace from=".LFXO > .pin1" to=".C_LFXO1 > .pin1" />
      <trace from=".C_LFXO1 > .pin2" to="net.GND" />
      <trace from=".LFXO > .pin2" to=".C_LFXO2 > .pin1" />
      <trace from=".C_LFXO2 > .pin2" to="net.GND" />

      <chip
        name="J1"
        footprint="pinrow10_p1.27mm"
        schX={16}
        schY={0}
        schWidth={6}
        pinLabels={{
          pin1: "VREF",
          pin2: "SWDIO",
          pin3: "GND",
          pin4: "SWDCLK",
          pin5: "GND2",
          pin6: "SWO",
          pin7: "NC",
          pin8: "NC2",
          pin9: "GNDDetect",
          pin10: "RESET"
        }}
        schPinArrangement={{
          leftSide: { direction: "top-to-bottom", pins: ["VREF", "SWDIO", "GND", "SWDCLK", "GND2"] },
          rightSide: { direction: "top-to-bottom", pins: ["SWO", "NC", "NC2", "GNDDetect", "RESET"] }
        }}
      />
      <trace from=".J1 > .VREF" to="net.VDD" />
      <trace from=".J1 > .GND" to="net.GND" />
      <trace from=".J1 > .GND2" to="net.GND" />
      <trace from=".J1 > .SWDIO" to=".U1 > .SWDIO" />
      <trace from=".J1 > .SWDCLK" to=".U1 > .SWDCLK" />
      <trace from=".J1 > .RESET" to=".U1 > .RESET" />

      <netlabel schX={7} schY={3.7} net="VDD" connection="C1.pin1" anchorSide="left" />
      <netlabel schX={7} schY={2.7} net="VDD" connection="C2.pin1" anchorSide="left" />
      <netlabel schX={7} schY={1.7} net="VDD" connection="C3.pin1" anchorSide="left" />
      <netlabel schX={7} schY={0.7} net="VDD" connection="C4.pin1" anchorSide="left" />
      <netlabel schX={9.5} schY={-0.5} net="VDD" connection="CBULK.pin1" anchorSide="right" />
    </subcircuit>
  </board>
)