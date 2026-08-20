// Hand-cut (jigsaw + drill + tape measure) geometry for the two cable cage
// plates, derived from static/dxf/cable-cage-{top,bottom}.dxf (mm, origin at
// plate centre, y up).
//
// Both plates share ONE outline: a regular hexagon, flats left/right, points
// up/down. Across flats (horizontal) = side·√3, across corners (vertical) =
// 2·side, so it lays out and self-checks exactly like the top plate.
//
// Holes, straight off the DXF:
//   - centre: a single Ø177 round hole (chute-mount clearance).
//   - six Ø5.5 mounting holes on a 175 mm-radius bolt circle, one every 60°
//     (i.e. one just inside each hex corner) — these take the M5 screws.
//   - TOP plate only: twelve Ø3.5 holes on a 152 mm radius, in six pairs
//     centred on each edge, plus a keyed notch on one side of the centre hole.
//
// The twelve Ø3.5 holes are a real cut feature but the documented top-interface
// build never fastens anything into them, so the guide flags them as optional.

export type Units = 'mm' | 'in'; // (re-exported shape; helpers come from $lib/handcut)

export const CAGE_HEX = {
	side: 187.64, // also centre → corner (a hexagon's side equals its circumradius)
	acrossFlats: 325.0, // horizontal, flat to flat
	acrossCorners: 375.28, // vertical, point to point
	cornerOffset: 93.82, // side/2: the side corners above/below the horizontal centreline
	diagonal: 496.44 // stock rectangle corner-to-corner (√(325² + 375.28²)), for the squareness check
};

// stock rectangle = hexagon bounding box
export const CAGE_RECT = { w: CAGE_HEX.acrossFlats, h: CAGE_HEX.acrossCorners };

export const CAGE_CENTER_HOLE_D = 177; // Ø177 centre opening (jigsaw)
export const MOUNT_HOLE_D = 5.5; // six corner mounting holes (M5)
export const MOUNT_RING_R = 175; // their bolt-circle radius
export const CLAMP_HOLE_D = 3.5; // twelve small holes, top plate only
export const CLAMP_RING_R = 151.8; // their radius

/** Six mounting holes: 60° apart on MOUNT_RING_R, one just inside each corner. */
export const MOUNT_ANGLES = [30, 90, 150, 210, 270, 330];

/** The twelve Ø3.5 holes (top plate), plate coords, y up. Six pairs, one on
 *  each edge midline, 40 mm apart. */
export const CLAMP_HOLES: { x: number; y: number }[] = [
	{ x: -150.5, y: 20 },
	{ x: -150.5, y: -20 },
	{ x: -57.93, y: 140.34 },
	{ x: -92.57, y: 120.34 },
	{ x: 92.57, y: 120.34 },
	{ x: 57.93, y: 140.34 },
	{ x: 150.5, y: -20 },
	{ x: 150.5, y: 20 },
	{ x: 57.93, y: -140.33 },
	{ x: 92.57, y: -120.33 },
	{ x: -57.93, y: -140.33 },
	{ x: -92.57, y: -120.33 }
];

/** Keyed notch (top plate). A pocket bulging outward from the Ø177 hole:
 *  inner edge is the centre hole (r 88.5), outer edge an arc at r 104.5, so the
 *  pocket is exactly 16 mm deep. Drilling one Ø16 hole at each end (centre on a
 *  96.5 mm radius) forms the rounded ends; saw the outer wall between them. The
 *  notch is centred on the radius to a corner bolt hole (210° in the DXF), and
 *  since the plate is otherwise six-fold symmetric it can face any corner. */
export const KEY = {
	innerR: 88.5, // = CAGE_CENTER_HOLE_D / 2
	outerR: 104.5,
	depth: 16, // outerR − innerR
	bit: 16, // Ø16 (5/8″) drill for each end
	centreR: 96.5, // radius the two drill centres sit on
	spacing: 78.5, // centre-to-centre of the two drill holes
	alongArc: 40, // step each way along the 96.5 arc from the corner radius
	// two drill centres, plate coords (y up), on the 210° radius ±24°
	drills: [
		{ x: -96.0, y: -10.1 },
		{ x: -56.7, y: -78.1 }
	],
	// outer arc extent and the centre-hole gap, degrees (DXF, standard math angle)
	outerFromDeg: 187.98,
	outerToDeg: 232.02,
	innerFromDeg: 182.96,
	innerToDeg: 237.04
};
