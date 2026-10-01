// Where the machine's bins and chute are in the model, from the backend's own
// numbers: the bin layout (GET /api/bins/layout) and the chute's geometry
// (GET /api/hardware-config/chute). Pure functions, so the page and the view
// agree and neither needs three.js to answer "which bin is this".
import { binCenterAngle, normDeg, reachInfo, type ChuteGeometry } from '$lib/chute/geometry';
import type { Manifest } from './model';

export type LayoutBin = {
	section_index: number;
	bin_index: number;
	global_index: number;
	size: string;
	category_ids: string[];
	not_in_inventory: boolean;
};
export type LayoutLayer = {
	layer_index: number;
	enabled: boolean;
	section_count: number;
	section_enabled: boolean[];
	bin_count: number;
	bins: LayoutBin[];
};

export type Geometry = ChuteGeometry & { maxAngleDeg: number };

/** Each layer's chute and bin kind, from the top: three bins a section is
 *  'third', two is 'half', and any other count draws as 'third'. */
export function layerKinds(layers: LayoutLayer[]): string[] {
	return [...layers]
		.sort((a, b) => a.layer_index - b.layer_index)
		.map((l) => (Math.round(l.bin_count / Math.max(1, l.section_count)) === 2 ? 'half' : 'third'));
}

/** One bin as the model draws it. */
export type BinPlace = {
	key: string;
	layer: number;
	section: number;
	bin: number;
	binsInSection: number;
	globalIndex: number;
	categoryIds: string[];
	notInInventory: boolean;
	// Off: the layer or section is disabled.
	enabled: boolean;
	// Past the chute's travel.
	reachable: boolean;
	// Where the chute is when it points at this bin, in chute degrees.
	chuteAngle: number;
	// How to draw it: which bin kind, on which ring, turned to which face, and
	// for a count the CAD has no bins for, how far along the face and how wide.
	kind: string;
	level: number;
	faceAzimuth: number;
	along: number;
	widthScale: number;
};

export const binKey = (layer: number, section: number, bin: number) => `${layer}:${section}:${bin}`;

/** Every bin's card is laid out at this size, in CSS pixels, and the view
 *  scales it to fit the narrowest bin's front, so all the cards are one size. */
export const CARD_SIZE = { width: 176, height: 78 };

const wrap = (deg: number) => (((deg % 360) + 540) % 360) - 180;

/** The chute's degrees turn clockwise from home, seen from above; azimuths turn
 *  counterclockwise. Section 0's face is the one nearest where the chute points
 *  at section 0's centre, counting from where the CAD says home is. Faces sit
 *  on section centres, so the chute always lines up with the bins it aims at. */
export function chuteFrame(geo: ChuteGeometry, manifest: Manifest) {
	const pitch = 360 / Math.max(1, geo.numSections);
	const sectionCentre = geo.firstSectionOffsetDeg + geo.sectionWidthDeg / 2;
	const guess = manifest.homeAzimuth - sectionCentre;
	const face0 = manifest.faces.reduce((best, f) =>
		Math.abs(wrap(f - guess)) < Math.abs(wrap(best - guess)) ? f : best
	);
	return {
		/** The outlet's azimuth (degrees) when the chute is at `angle`. */
		azimuth: (angle: number) => face0 + sectionCentre - angle,
		faceOf: (section: number) => face0 - section * pitch
	};
}

// The CAD's bins on a face, in the order the backend counts them: bin 0 is
// the first the chute reaches turning clockwise, the counterclockwise end.
const KINDS: Record<number, string[]> = {
	2: ['half_right', 'half_left'],
	3: ['third_right-back', 'third_center', 'third_left']
};

export function placeBins(layers: LayoutLayer[], geo: Geometry, manifest: Manifest): BinPlace[] {
	const frame = chuteFrame(geo, manifest);
	// A face's usable width, from the CAD's three bins side by side.
	const third = manifest.binKinds['third_center'];
	const thirdWidth = third ? third.max[2] - third.min[2] : 0.16;
	const places: BinPlace[] = [];
	for (const layer of layers) {
		const perSection = new Map<number, number>();
		for (const b of layer.bins)
			perSection.set(b.section_index, (perSection.get(b.section_index) ?? 0) + 1);
		for (const b of layer.bins) {
			const k = perSection.get(b.section_index) ?? 1;
			const angle = binCenterAngle(geo, b.section_index, b.bin_index, k);
			const cad = KINDS[k];
			const faceWidth = thirdWidth * 3;
			places.push({
				key: binKey(layer.layer_index, b.section_index, b.bin_index),
				layer: layer.layer_index,
				section: b.section_index,
				bin: b.bin_index,
				binsInSection: k,
				globalIndex: b.global_index,
				categoryIds: b.category_ids,
				notInInventory: b.not_in_inventory,
				enabled: layer.enabled && (layer.section_enabled[b.section_index] ?? true),
				reachable: reachInfo(angle, geo.maxAngleDeg).reachable,
				// The backend aims at the angle on the circle, as reachInfo does.
				chuteAngle: normDeg(angle),
				kind: cad ? cad[b.bin_index] : 'third_center',
				level: layer.layer_index,
				faceAzimuth: frame.faceOf(b.section_index),
				// Toward -z is counterclockwise on the face, where bin 0 is.
				along: cad ? 0 : -faceWidth / 2 + ((b.bin_index + 0.5) * faceWidth) / k,
				widthScale: cad ? 1 : 3 / k
			});
		}
	}
	return places;
}
