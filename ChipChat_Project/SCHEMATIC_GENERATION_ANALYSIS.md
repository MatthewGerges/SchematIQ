# Schematic Generation Analysis

## Missing Information for KiCad Schematic Generation

Based on comparing `project_dummy.json` with actual KiCad `.kicad_sch` files, here's what's missing:

### 1. **Component Placement & Layout**
- **Position (x, y coordinates)**: Currently missing. Needed for `(at x y angle)` in KiCad
- **Orientation/angle**: Needed (0, 90, 180, 270 degrees)
- **Mirror**: Some components need `(mirror x)` or `(mirror y)`
- **Unit selection**: For multi-unit symbols (e.g., gates in logic ICs)

**Example from KiCad:**
```
(symbol
  (lib_id "Diode:SMAJ6.5CA")
  (at 148.59 100.33 270)  ← position and angle
  (mirror x)              ← mirroring
  ...
)
```

### 2. **Wires (Physical Connections)**
- **Wire segments**: Start/end coordinates for each wire segment
- **Wire routing**: How wires are routed between components (not just logical connections)
- **Junctions**: Where wires meet (x, y coordinates)

**Current state**: We have logical connections (pin → net), but not physical wire paths.

### 3. **Labels (Net Names)**
- **Local labels**: Position, orientation, and text for local net labels
- **Hierarchical labels**: Position, shape (input/output/bidirectional), and orientation
- **Power symbols**: Position for GND, +5V, +3.3V symbols

**Example:**
```
(label "PP_5V_VBUS"
  (at 167.64 66.04 0)
  (effects (font (size 1.27 1.27)))
  ...
)
(hierarchical_label "USB_DN"
  (shape output)
  (at 119.38 86.36 0)
  ...
)
```

### 4. **Hierarchical Sheet Structure**
- **Sheet instances**: Position, size, and file reference for sub-sheets
- **Sheet pins**: Position and net connections for hierarchical sheet pins
- **Sheet-to-sheet connections**: How hierarchical labels connect across sheets

### 5. **Symbol Library References**
- **lib_id format**: Full library path (e.g., `"Connector:USB_C_Receptacle_USB2.0_16P"` vs just `"USB_C_Receptacle_USB2.0_16P"`)
- **Symbol library path**: Where to find the `.kicad_sym` file
- **Footprint library path**: Where to find the `.kicad_mod` file

### 6. **Component Properties**
- **Additional properties**: Datasheet URLs, manufacturer, part numbers, custom fields
- **Property positions**: Where each property is placed relative to component
- **Property visibility**: Which properties are hidden

### 7. **Passive Component Details**
- **Symbol type**: Generic (Device:R, Device:C) vs specific part numbers
- **Footprint assignments**: Specific footprint names for passives
- **Value formatting**: How values are displayed

### 8. **Visual/Layout Information**
- **Text annotations**: Notes, titles, revision info
- **Drawing elements**: Lines, rectangles, circles for visual organization
- **Page layout**: Title block, page numbers

---

## LLM Generation Approaches & Tradeoffs

### **Approach A: End-to-End Generation (Single Prompt)**

**Input:**
- Component list (from `components.json` database)
- Description of system functionality
- Optional: High-level block diagram or flow description

**Output:**
- Complete `project.json` with all connections, passives, nets, and positions

**Pros:**
- Simple API interface
- LLM can reason about entire system holistically
- Can optimize layout and routing together
- Single pass = faster

**Cons:**
- Very large context window needed
- Hard to debug/validate intermediate steps
- LLM might miss edge cases or make inconsistent decisions
- Difficult to iterate on specific sections
- High token cost per generation

**Best for:** Simple designs, proof-of-concept, when you trust LLM completely

---

### **Approach B: Multi-Stage Pipeline (Recommended)**

**Stage 1: Component Selection & Assignment**
- **Input**: Description, component database
- **Output**: List of components with reference designators, sheet assignments
- **LLM Task**: "Given this description, select appropriate components from database"

**Stage 2: Net Generation**
- **Input**: Component list, description, component pin details from database
- **Output**: Net list with connections (what we have now in `nets` section)
- **LLM Task**: "Connect these components based on the description and pin functions"

**Stage 3: Passive Component Addition**
- **Input**: Core components, nets, component datasheets/notes
- **Output**: Passive components (resistors, capacitors) with values and connections
- **LLM Task**: "Add required passives (decoupling caps, pull-ups, etc.) based on component requirements"

**Stage 4: Layout & Routing (Optional - could be algorithmic)**
- **Input**: Components, nets, connections
- **Output**: Component positions, wire routes, label positions
- **LLM Task**: "Place components and route wires for clean schematic layout" OR use constraint solver

**Pros:**
- Easier to validate each stage
- Can fix errors at specific stages
- Smaller, focused prompts = better LLM performance
- Can mix LLM + algorithmic approaches
- Easier to cache/reuse intermediate results
- Better error messages

**Cons:**
- More complex pipeline
- Need to manage state between stages
- Potential for inconsistencies between stages
- More API calls

**Best for:** Production systems, complex designs, when you need reliability

---

### **Approach C: Hybrid (LLM + Rules Engine)**

**LLM generates:**
- Component selection
- Net connections (logical)
- Passive component requirements

**Rules engine/algorithm generates:**
- Component positions (using force-directed layout or grid-based)
- Wire routing (using pathfinding algorithms)
- Label placement (automatic based on wire positions)

**Pros:**
- Best of both worlds: LLM reasoning + deterministic layout
- Predictable, consistent layouts
- Faster (layout is algorithmic)
- Easier to debug

**Cons:**
- Need to build layout algorithms
- May not match human aesthetic preferences
- Less flexible for special cases

**Best for:** When you want consistent, automated layouts

---

### **Approach D: Template-Based with LLM Filling**

**Pre-defined templates:**
- Common circuit patterns (power supply, I2C bus, USB interface)
- Layout templates for different sheet types

**LLM task:**
- Select appropriate templates
- Fill in component-specific details
- Connect templates together

**Pros:**
- Consistent, proven layouts
- Faster generation
- Lower token costs
- Easier validation

**Cons:**
- Less flexible
- Need to maintain template library
- May not handle novel designs well

**Best for:** Standard designs, when you have common patterns

---

## Recommended Input Structure for LLM

### **Minimal Input (Approach A or B Stage 1-2):**
```json
{
  "description": "USB-C powered BME280 sensor board...",
  "components": [
    {"part": "USB_C_Receptacle_USB2.0_16P", "purpose": "Power and USB data input"},
    {"part": "TPS628438DRL", "purpose": "5V to 3.3V buck converter"},
    {"part": "MCP2221A-I_SL", "purpose": "USB to I2C bridge"},
    {"part": "BME280", "purpose": "Environmental sensor"}
  ],
  "component_database": {...},  // Full or filtered component specs
  "constraints": {
    "voltage_levels": ["5V", "3.3V"],
    "interfaces": ["USB", "I2C"]
  }
}
```

### **Enhanced Input (For Better Results):**
```json
{
  "description": "...",
  "components": [...],
  "component_database": {...},
  "design_requirements": {
    "power_consumption": "low",
    "board_size": "small",
    "cost_sensitive": true
  },
  "reference_designs": [...],  // Similar designs for context
  "design_patterns": {
    "power_supply": "buck_converter",
    "i2c_bus": "standard_with_pullups"
  }
}
```

---

## Missing Data Structure Additions

### **For Component Placement:**
```json
{
  "ref": "J1",
  "part": "USB_C_Receptacle_USB2.0_16P",
  "sheet": "USBC",
  "position": {"x": 63.5, "y": 86.36, "angle": 0},
  "mirror": null,
  "connections": [...]
}
```

### **For Wires:**
```json
{
  "nets": [{
    "name": "PP_5V_VBUS",
    "type": "local",
    "connections": [...],
    "wires": [
      {"from": {"ref": "J1", "pin": "A4"}, "to": {"x": 63.5, "y": 71.12}},
      {"from": {"x": 63.5, "y": 71.12}, "to": {"x": 210.82, "y": 71.12}},
      ...
    ],
    "labels": [
      {"text": "PP_5V_VBUS", "position": {"x": 167.64, "y": 66.04}}
    ]
  }]
}
```

### **For Hierarchical Sheets:**
```json
{
  "sheets": [{
    "name": "USBC",
    "file": "USBC.kicad_sch",
    "page": 2,
    "hierarchical_labels": [
      {
        "name": "USB_DN",
        "shape": "output",
        "position": {"x": 119.38, "y": 86.36},
        "net": "USB_DN"
      }
    ]
  }]
}
```

---

## Recommendations

1. **Start with Approach B (Multi-Stage)** - Most flexible and debuggable
2. **Use Approach C (Hybrid)** for layout - Let LLM do reasoning, algorithms do positioning
3. **Add position data incrementally** - Start with logical connections, add layout later
4. **Keep current JSON structure** - It's good for logical connections, just needs layout additions
5. **Consider separate "layout.json"** - Keep logical connections separate from physical layout for flexibility
