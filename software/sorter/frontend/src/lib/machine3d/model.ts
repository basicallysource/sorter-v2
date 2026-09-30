// The machine's 3D model: the file on the asset service, and what it says
// about itself. scripts/machine-model/build.mjs makes the file from the CAD and
// puts this description in its asset.extras.machine; model.json pins the file
// by its hash, so a URL always means the same bytes and caches forever.
import pin from './model.json';

export const MODEL: { url: string; bytes: number } = pin;

export type Vec3 = [number, number, number];

/** A ring of bins in the CAD, from the top: its kind, where its bins stand and
 *  where its layer's flap turns (a point and an axis, in the chute's frame). */
export type Level = {
	kind: 'half' | 'third';
	base: number;
	top: number;
	flap: { origin: Vec3; axis: Vec3 } | null;
};

export type Manifest = {
	version: 1;
	units: 'm';
	up: 'y';
	box: [Vec3, Vec3];
	levels: Level[];
	// The hexagon's faces, as azimuths in degrees (counterclockwise seen from above).
	faces: number[];
	// One bin of each kind, in the frame of the face at azimuth 0 with its ring's
	// base at y = 0: its bounding box. The model has a mesh for each.
	binKinds: Record<string, { min: Vec3; max: Vec3 }>;
	// Where the chute's outlet points when the chute is home, from the CAD.
	homeAzimuth: number;
	rotors: { name: string; at: [number, number] }[];
	motors: string[];
};
