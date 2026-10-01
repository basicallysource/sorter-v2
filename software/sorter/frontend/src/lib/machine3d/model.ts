// The machine's 3D model: the file on the asset service, and what it says
// about itself. scripts/machine-model/build.mjs makes the file from the CAD and
// puts this description in its asset.extras.machine; model.json pins the file
// by its hash, so a URL always means the same bytes and caches forever.
//
// Its nodes are named without spaces: top, base, layer and layer-posts (one
// layer's frame, which the page stacks), chute with chute-top and chute-third /
// chute-half (a chute layer of each kind, with flap-third and servo-third or
// flap-half and servo-half),
// rotor-c_channel_1 and the rest, motor-chute and the rest, and bin-kinds with
// bin-third_left and the rest.
import pin from './model.json';

export const MODEL: { url: string; bytes: number } = pin;

export type Vec3 = [number, number, number];

/** A ring of bins in the CAD, from the top: its kind and where its bins stand. */
export type Level = { kind: 'half' | 'third'; base: number; top: number };

export type Manifest = {
	version: 2;
	units: 'm';
	up: 'y';
	box: [Vec3, Vec3];
	levels: Level[];
	// How far apart layers are: the page hangs the machine's layers this far
	// apart under the top ring.
	pitch: number;
	// Each chute layer kind's flap hinge, a point and an axis in its layer's frame.
	flaps: Record<string, { origin: Vec3; axis: Vec3 }>;
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
