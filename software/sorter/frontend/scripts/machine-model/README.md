# The 3D machine

The UI's 3D page (`src/routes/3d`) draws the sorter from one small glTF
file built from the machine's CAD. The file lives on the asset service, and
`src/lib/machine3d/model.json` pins it by URL. The asset service names every
file after a hash of its bytes, so a URL always means the same model and a
browser caches it for good. No model file goes in git.

## Making a new model

1. Export the main assembly from Onshape as glTF through the translation
   API (`POST /api/assemblies/d/{d}/w/{w}/e/{e}/translations` with
   `formatName: "GLTF"`, `flattenAssemblies: false`, `yAxisUp: false`). The
   tolerances used for the current model: `angularTolerance` 0.15,
   `distanceTolerance` 0.0008, `maximumChordLength` 0.04. The direct
   `/gltf` endpoint ignores tolerances, so use the translation.
2. Build: `node scripts/machine-model/build.mjs EXPORT.gltf machine.glb`
   (about 10 seconds; it needs `--max-old-space-size=8000` for a large
   export). It prints what it kept, how many triangles it stores and draws,
   the draw calls, and the file's size.
3. Publish: this uploads it and rewrites `model.json`; commit `model.json`.

   ```sh
   ASSET_SERVICE_URL=... ASSET_SERVICE_TOKEN=... node scripts/machine-model/publish.mjs machine.glb
   ```

## What the builder does

- Leaves out fasteners, inserts, wiring, the electronics inside their
  housings and anything under 8 mm across (`DROP`, `KEEP`, `MIN_PART`).
- Simplifies every surface to within 0.5 mm of the CAD's. Welding joins
  faces that meet smoothly and leaves each crease as a seam the simplifier
  keeps, so flat faces stay flat.
- Merges the parts used once, per look (`body`, `dark`), and stores a part
  used more than once a single time, instanced (`EXT_mesh_gpu_instancing`).
- Splits the tower into parts the page stacks for the machine's own number
  of layers: the top (feeder, chute drive, electronics), which stays where
  the CAD has it; one layer's frame (`layer`) and its posts
  (`layer-posts`, left out under the lowest layer, which stands on the base's
  legs), taken from the second layer, since every layer's frame is the same;
  and the base (legs, casters, the chute's bottom mount), which goes under
  the lowest layer. Layers are `pitch` (160 mm) apart.
- Keeps apart what moves or lights up: `chute` (turns about the vertical
  axis) with `chute-top` and one chute layer of each kind, `chute-third` and
  `chute-half` (their funnels differ), each with its door (`flap-third`,
  `flap-half`, on the hinge from the CAD's revolute mate) and servo;
  `rotor-NAME` for each feeder rotor; `motor-NAME` for each motor, named as
  the backend names its steppers.
- Keeps one bin of each kind under `bin-kinds`, in the frame of the face
  at azimuth 0 with its ring's base at height 0. The page places bins from
  the machine's own layout (`GET /api/bins/layout`), so a machine with more
  or fewer layers, or other bins per section, is drawn as it is.
- Compresses with meshopt and quantizes. A node that holds a mesh gets the
  quantization's scale and offset, so every pivot the page turns is a node
  of its own with the mesh on a child.
- Writes `asset.extras.machine` (typed in `src/lib/machine3d/model.ts`):
  the CAD's bin rings from the top, the layer pitch, each chute kind's flap
  hinge, the bin kinds' boxes, the hexagon's faces, and where the chute
  points when it is home, measured from the limit switch and the stop that
  turns with the chute.

Node names have no spaces and no repeats: three.js's loader turns a space
into an underscore and renames a repeated name.

## On the page

`src/lib/machine3d/view.ts` draws only when something changed (the camera,
the machine's state, an animation still running). The dev server's
`/3d?bench` times a frame, "see inside", a pick and a selection in the
browser it runs in.
