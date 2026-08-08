# basically Sorter - Electronics
This repository contains all electronics-related assets for the project, including schematics, PCB designs, 3D models, and wire harness definitions. The workflow is designed to be fully open source (see licenses for details), reproducible, and compatible with common free tools.

---

## Overview
This folder holds all materials needed to build, modify, or inspect the project's electronics systems. It includes:
- **KiCad** projects for schematics and PCB layout
- **Onshape** 3D CAD models (this is linked to the Main project onshape doc)
- **WireViz** YAML harness definitions 
- Information on how to submit to each section will be provided in the respective subdirectory README files.

---

## KiCad Schematics & PCB
All schematics and PCB files are created using **KiCad**.

### Contents:
- `/kicad/` directory contains the KiCad project folders for each PCB
- PCB and schematic source files (`.kicad_sch`, `.kicad_pcb`)
- Symbol and footprint libraries

### Requirements:
- KiCad **v9 or later** (recommended since we use tools in KiCad that follow this requirement)

---

## 3D Models (Onshape)
Mechanical components, board outlines, enclosures, and mounting hardware are modeled in **Onshape**.

### Access:
- Public Onshape document link located in `/3d/README.md`
- Exports (`.step`, `.stl`) are mirrored in the repo for convenience

### Notes:
- Any modifications should be made in KiCad and then re-exported as step and stl. Then uploaded to Onshape under the kiCad imports folder.

---

## Wire Harness Generation
This project uses the **command‑line wire harness generator** used by *LumenPnP* (project: **`wireviz`**—a YAML‑based wiring harness generator).

### Tool Used:
- **WireViz** (https://github.com/wireviz/wireviz)

### Features:
- Generates wiring diagrams from YAML files
- Produces PDF, PNG, and interactive outputs

### How it runs here
The sources are `wire_harness/*.yml`. **They are the only thing you edit, and
the only thing in git.** Everything rendered from them (PNG, SVG, PDF, HTML,
per-cable BOM, and the supplier RFQ zip) is published by CI to the assets
bucket under the branch name, and the docs site links it at
[/hardware/electronics/wireviz/](https://docs.basically.website/hardware/electronics/wireviz/).

Edit the YAML, push, open a PR. That's the whole workflow: no toolchain, no
credentials, no publish step to remember. The PR's docs preview shows the PR's
own drawings about 90 seconds after each push. Details, including local
rendering and how to add a drawing: `wire_harness/AGENTS.md`.

---

##  Repository Structure
```
/electronics
   ├── kicad/               # Schematics and PCB
   ├── 3d/                  # 3D models (KiCad exports)
   ├── wire_harness/        # WireViz YAML harness definitions
   ├── assets/              # Images, diagrams, renders
   ├── bom/                 # Top level Bill of Material for all electronics
   └── README.md            # This file
```

---
## License
See the Liscense information in the main project.

---

For questions or contributions, please open an issue or pull request in the main repository or check the Discord Server
