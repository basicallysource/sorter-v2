# bom-helpers

> ⚠️ Based on an in-progress version of the CAD. Some assemblies are disjoint or incomplete. The assumptions baked into these scripts will decay as the model changes.

Exists for two reasons:

1. **Programmatic cleanup / changes to BOMs** exported from Onshape.
2. **Recovering extrusion lengths.** Onshape doesn't seem to let you export frames / aluminum profile parts with their name *and* their length at the same time from an assembly. The part studio cut list has lengths but no names; the assembly BOM has names but no lengths (unless you stuff them into the description field by hand, which is error-prone). This script re-fills lengths by measuring the STLs from a big assembly export.

## What it produces

Given the main assembly BOM + the interface layer BOM + the main assembly STL zip (extracted into `stl-downloads/`), produces:

- `bom-outputs/per_layer.csv` — screws, nuts, heat-set inserts, and aluminum extrusions for one layer.
- `bom-outputs/per_machine.csv` — same categories totaled for a whole machine (interface + feeder + one layer).

3D-printed parts and electronics are not in scope and are dropped from the output.

## Running

Uses `uv`. First time:

```
uv sync
```

Measure STLs (useful on its own — dumps bounding boxes and PCA-OBB lengths for everything in `stl-downloads/`):

```
uv run measure_stl.py
```

Build the enriched per-layer / per-machine CSVs:

```
uv run build_bom.py
```
