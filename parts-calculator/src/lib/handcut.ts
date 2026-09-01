// Hand-cut (jigsaw + drill + tape measure) geometry for the top plate,
// derived from static/dxf/top-plate.dxf (mm, origin at plate center, y up).
//
// The plate is a regular hexagon, flats left/right:
//   drawn side segments 363.974 mm + R21 corner fillets that each consume
//   21·tan(30°) = 12.124 mm  →  true side = 388.223 mm = circumradius.
// The 5 rounded cable slots are replaced by single Ø22 mm drill holes at the
// slot centers (two slots are 18 mm wide; 22 is a hair proud — they only pass
// cables). Everything else is measured straight off the DXF.

export const HEX = {
	side: 388.223, // also center → corner (a hexagon's side equals its circumradius)
	acrossFlats: 672.421,
	acrossCorners: 776.445,
	apothem: 336.211, // center → middle of a flat side
	cornerOffset: 194.111, // side/2: hexagon corner above/below the horizontal centerline
	filletR: 21, // original rounded corners (optional when hand cutting)
	diagonal: 1027.09 // stock rectangle corner-to-corner, for the squareness check
};

// stock rectangle = hexagon bounding box (ignoring corner fillets)
export const RECT = { w: HEX.acrossFlats, h: HEX.acrossCorners };

export const CENTER_HOLE_D = 199.9; // jigsaw opening at plate center
export const SMALL_HOLE_D = 5.5;
export const CABLE_HOLE_D = 22; // also doubles as the jigsaw blade-entry hole

export const RING_INNER_R = 213.06; // 6-hole ring; neighbor-to-neighbor chord = radius
export const RING_OUTER_R = 324.96;

export type HoleGroup = 'stepper' | 'inner' | 'outer' | 'cable';
export type Hole = { id: string; x: number; y: number; d: number; group: HoleGroup };

export const HOLES: Hole[] = [
	// stepper trio, on the horizontal centerline
	{ id: 'S1', x: -145, y: 0, d: SMALL_HOLE_D, group: 'stepper' },
	{ id: 'S2', x: -180, y: 0, d: SMALL_HOLE_D, group: 'stepper' },
	{ id: 'S3', x: -210, y: 0, d: SMALL_HOLE_D, group: 'stepper' },
	// inner ring of 6, r = 213.06
	{ id: 'I1', x: 198.394, y: 77.685, d: SMALL_HOLE_D, group: 'inner' },
	{ id: 'I2', x: 31.92, y: 210.657, d: SMALL_HOLE_D, group: 'inner' },
	{ id: 'I3', x: -166.474, y: 132.972, d: SMALL_HOLE_D, group: 'inner' },
	{ id: 'I4', x: -198.394, y: -77.685, d: SMALL_HOLE_D, group: 'inner' },
	{ id: 'I5', x: -31.92, y: -210.657, d: SMALL_HOLE_D, group: 'inner' },
	{ id: 'I6', x: 166.474, y: -132.972, d: SMALL_HOLE_D, group: 'inner' },
	// outer ring of 6, r = 324.96
	{ id: 'O1', x: 264.287, y: 189.087, d: SMALL_HOLE_D, group: 'outer' },
	{ id: 'O2', x: -31.61, y: 323.423, d: SMALL_HOLE_D, group: 'outer' },
	{ id: 'O3', x: -295.898, y: 134.336, d: SMALL_HOLE_D, group: 'outer' },
	{ id: 'O4', x: -264.287, y: -189.087, d: SMALL_HOLE_D, group: 'outer' },
	{ id: 'O5', x: 31.61, y: -323.423, d: SMALL_HOLE_D, group: 'outer' },
	{ id: 'O6', x: 295.898, y: -134.336, d: SMALL_HOLE_D, group: 'outer' },
	// cable holes: one big hole at each original slot's center
	{ id: 'C1', x: -291, y: 0, d: CABLE_HOLE_D, group: 'cable' },
	{ id: 'C2', x: -145.5, y: 252.014, d: CABLE_HOLE_D, group: 'cable' },
	{ id: 'C3', x: -86.475, y: 149.779, d: CABLE_HOLE_D, group: 'cable' },
	{ id: 'C4', x: -86.475, y: -149.779, d: CABLE_HOLE_D, group: 'cable' },
	{ id: 'C5', x: -145.5, y: -252.014, d: CABLE_HOLE_D, group: 'cable' }
];

/** The original rounded cable slots (shown as ghosts in the hole map).
 *  cx/cy in plate coords, L along the slot, W across, rot in SVG degrees. */
export const CABLE_SLOTS = [
	{ cx: -291, cy: 0, L: 22, W: 72, rot: 0 },
	{ cx: -145.5, cy: 252.014, L: 72, W: 22, rot: -30 },
	{ cx: -86.475, cy: 149.779, L: 48, W: 18, rot: -30 },
	{ cx: -86.475, cy: -149.779, L: 48, W: 18, rot: 30 },
	{ cx: -145.5, cy: -252.014, L: 72, W: 22, rot: 30 }
];

/** Measured from the stock rectangle's left/bottom edges (do layout before
 *  cutting the corners — the factory edges are the reference). */
export function fromEdges(h: { x: number; y: number }): { left: number; bottom: number } {
	return { left: h.x + RECT.w / 2, bottom: h.y + RECT.h / 2 };
}

export type Units = 'mm' | 'in';

/** mm as a tape-measure-friendly inch fraction, nearest 1/32″ (≤ 0.4 mm off). */
export function inchStr(mm: number, denom = 32): string {
	const total = Math.round((mm / 25.4) * denom);
	const whole = Math.floor(total / denom);
	let num = total - whole * denom;
	let d = denom;
	if (num === 0) return `${whole}″`;
	while (num % 2 === 0) {
		num /= 2;
		d /= 2;
	}
	return whole ? `${whole} ${num}/${d}″` : `${num}/${d}″`;
}

export function fmtLen(mm: number, units: Units): string {
	return units === 'mm' ? `${mm.toFixed(1)} mm` : inchStr(mm);
}

/** Drill bits aren't unit conversions — each system has its own stock size. */
export function bitLabel(d: number, units: Units): string {
	if (units === 'mm') return `${d} mm`;
	const imperial: Record<number, string> = {
		[SMALL_HOLE_D]: '7/32″',
		[CABLE_HOLE_D]: '7/8″'
	};
	return imperial[d] ?? inchStr(d);
}
