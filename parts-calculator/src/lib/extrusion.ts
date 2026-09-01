// Procedural 2020 T-slot aluminium extrusion geometry.
//
// The cross-section is traced as one closed loop: a 20×20 outer square whose
// four faces each dip inward to form a T-slot channel, with a central bore as a
// hole. It's extruded to whatever length a piece needs, so renders stay correct
// for any length the cut-plan produces — nothing is pre-baked.

import * as THREE from 'three';

// profile constants (mm) — tweak here to match real stock exactly
const H = 10; // half of the 20 mm outer width
const A = 3; // half the slot opening at the face (6 mm slot)
const B = 5.5; // half-width of the channel behind the opening (the T undercut)
const T = 1.8; // face-plate thickness before the undercut opens
const D = 6; // channel depth from the face
const BORE_R = 2.5; // central bore radius

// silvery anodized aluminium; set to 0x24262a for the real black-anodized look
export const ALU_COLOR = 0xb9bec2;

function rot90([x, y]: [number, number], k: number): [number, number] {
	// rotate clockwise by 90°·k: (x,y) -> (y,-x)
	let px = x,
		py = y;
	for (let i = 0; i < k; i++) {
		const nx = py;
		const ny = -px;
		px = nx;
		py = ny;
	}
	return [px, py];
}

export function profile2020(): THREE.Shape {
	// one face, left→right along the top edge (y = +H), dipping into the slot
	const topEdge: [number, number][] = [
		[-H, H], // top-left corner
		[-A, H], // face → left lip
		[-A, H - T], // into the opening (plate thickness)
		[-B, H - T], // undercut out to the channel
		[-B, H - D], // down the channel wall
		[B, H - D], // across the channel floor
		[B, H - T], // up the far channel wall
		[A, H - T], // back under the lip
		[A, H] // return to the face
	];

	const pts: [number, number][] = [];
	for (let k = 0; k < 4; k++) for (const p of topEdge) pts.push(rot90(p, k));

	const shape = new THREE.Shape();
	shape.moveTo(pts[0][0], pts[0][1]);
	for (let i = 1; i < pts.length; i++) shape.lineTo(pts[i][0], pts[i][1]);
	shape.closePath();

	const bore = new THREE.Path();
	bore.absarc(0, 0, BORE_R, 0, Math.PI * 2, false);
	shape.holes.push(bore);

	return shape;
}

export function extrusionGeometry(length: number): THREE.ExtrudeGeometry {
	const geo = new THREE.ExtrudeGeometry(profile2020(), {
		depth: length,
		steps: 1,
		bevelEnabled: true,
		bevelThickness: 0.35,
		bevelSize: 0.35,
		bevelSegments: 1
	});
	geo.computeVertexNormals();
	return geo;
}

export function aluminiumMaterial(): THREE.MeshStandardMaterial {
	return new THREE.MeshStandardMaterial({
		color: new THREE.Color(ALU_COLOR),
		metalness: 0.85,
		roughness: 0.34,
		envMapIntensity: 1.0
	});
}
