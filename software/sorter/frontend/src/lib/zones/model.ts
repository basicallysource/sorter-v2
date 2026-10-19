// A channel's zones, as the machine keeps them (backend/zones/model.py): a ring
// around the channel's center and three arcs along it, drop, exit and a precise
// sliver just before the exit. Angles are image angles in degrees, increasing
// clockwise on screen, around the center; a span runs forward from start to
// end, the way pieces travel. The ring's inner circle may have a center of its
// own (`inner_center`): the hub stands above the rotor, so from the camera it
// looks shifted against the rotor's edge. Pixels are the camera's, in the
// zones' own frame (`frame`).

export type ZoneName = 'drop' | 'precise' | 'exit';
export type Part = 'ring' | ZoneName;
export type Source = 'default' | 'drawn' | 'found' | 'learned';
export type Point = [number, number];
export type Span = { start: number; end: number };

export type ChannelZones = {
	channel: number;
	frame: [number, number];
	center: Point;
	inner_radius: number;
	outer_radius: number;
	exit_radius: number;
	inner_center?: Point | null;
	drop: Span;
	exit: Span;
	precise_width: number;
	reference_angle: number;
	locked: Part[];
	source: Partial<Record<Part, Source>>;
	updated_at?: number;
};

export const PARTS: Part[] = ['ring', 'drop', 'precise', 'exit'];
export const MIN_SPAN_DEG = 1;
export const MIN_RING_PX = 4;
// The inner circle's center stays within this share of its radius of the
// center, so every ray from the center leaves the inner circle once.
export const MAX_INNER_OFFSET = 0.9;

export function normalizeAngle(angle: number): number {
	return ((angle % 360) + 360) % 360;
}

export function forwardDeg(from: number, to: number): number {
	return normalizeAngle(to - from);
}

export function spanWidth(span: Span): number {
	const width = forwardDeg(span.start, span.end);
	return width > 0 ? width : 360;
}

export function spanMiddle(span: Span): number {
	return normalizeAngle(span.start + spanWidth(span) / 2);
}

export function spanContains(span: Span, angle: number): boolean {
	return forwardDeg(span.start, angle) < spanWidth(span);
}

export function precise(zones: ChannelZones): Span | null {
	if (zones.precise_width <= 0) return null;
	return { start: normalizeAngle(zones.exit.start - zones.precise_width), end: zones.exit.start };
}

export function zoneSpan(zones: ChannelZones, name: ZoneName): Span | null {
	return name === 'precise' ? precise(zones) : zones[name];
}

export function isLocked(zones: ChannelZones, part: Part): boolean {
	return zones.locked.includes(part);
}

export function polar(center: Point, radius: number, angle: number): Point {
	const rad = (angle * Math.PI) / 180;
	return [center[0] + radius * Math.cos(rad), center[1] + radius * Math.sin(rad)];
}

export function angleOf(center: Point, point: Point): number {
	return normalizeAngle((Math.atan2(point[1] - center[1], point[0] - center[0]) * 180) / Math.PI);
}

// The inner circle's center.
export function hub(zones: ChannelZones): Point {
	return zones.inner_center ?? zones.center;
}

// Where the ray from the center at `angle` leaves the inner circle.
export function innerPoint(zones: ChannelZones, angle: number): Point {
	if (!zones.inner_center) return polar(zones.center, zones.inner_radius, angle);
	const rad = (angle * Math.PI) / 180;
	const [dx, dy] = [Math.cos(rad), Math.sin(rad)];
	const [fx, fy] = [zones.center[0] - zones.inner_center[0], zones.center[1] - zones.inner_center[1]];
	const b = fx * dx + fy * dy;
	const t = -b + Math.sqrt(Math.max(0, b * b - (fx * fx + fy * fy - zones.inner_radius ** 2)));
	return [zones.center[0] + t * dx, zones.center[1] + t * dy];
}

// How far from the center the inner circle reaches.
function innerReach(zones: ChannelZones): number {
	const [hx, hy] = hub(zones);
	return zones.inner_radius + Math.hypot(hx - zones.center[0], hy - zones.center[1]);
}

function arcAngles(span: Span, stepDeg = 3): number[] {
	const width = spanWidth(span);
	const steps = Math.max(2, Math.ceil(width / stepDeg));
	return Array.from({ length: steps + 1 }, (_, i) => span.start + (width * i) / steps);
}

// A zone's area: an annular sector, its outer edge at the exit radius for the exit.
export function zonePolygon(zones: ChannelZones, name: ZoneName): Point[] | null {
	const span = zoneSpan(zones, name);
	if (!span) return null;
	const outer = name === 'exit' ? zones.exit_radius : zones.outer_radius;
	const angles = arcAngles(span);
	return [...angles.map((a) => polar(zones.center, outer, a)), ...[...angles].reverse().map((a) => innerPoint(zones, a))];
}

// The channel's area: the ring from the drop's start to the exit's end, its
// outer edge drawn in to the exit radius across the exit.
export function channelPolygon(zones: ChannelZones): Point[] {
	const travel: Span = { start: zones.drop.start, end: zones.exit.end };
	const width = spanWidth(travel);
	const cut = zones.exit_radius < zones.outer_radius - 1e-6;
	let exitFrom = forwardDeg(travel.start, zones.exit.start);
	if (exitFrom > width) exitFrom = 0;
	const steps = Math.max(2, Math.ceil(width / 3));
	const rels = new Set<number>(Array.from({ length: steps + 1 }, (_, i) => (width * i) / steps));
	if (cut) rels.add(exitFrom);
	const outer: Point[] = [];
	for (const rel of [...rels].sort((a, b) => a - b)) {
		const angle = travel.start + rel;
		if (cut && rel >= exitFrom - 1e-6) {
			if (Math.abs(rel - exitFrom) < 1e-6) outer.push(polar(zones.center, zones.outer_radius, angle));
			outer.push(polar(zones.center, zones.exit_radius, angle));
		} else {
			outer.push(polar(zones.center, zones.outer_radius, angle));
		}
	}
	const inner = arcAngles(travel)
		.reverse()
		.map((a) => innerPoint(zones, a));
	return [...outer, ...inner];
}

export function svgPath(points: Point[]): string {
	return points.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ') + ' Z';
}

// --- Edits: each returns new zones, marks what it changed as drawn, and keeps
// the ring and spans sound. ---

function drawn(zones: ChannelZones, part: Part): ChannelZones {
	return { ...zones, source: { ...zones.source, [part]: 'drawn' } };
}

function withSpan(zones: ChannelZones, name: 'drop' | 'exit', span: Span): ChannelZones {
	const start = normalizeAngle(span.start);
	let end = normalizeAngle(span.end);
	if (forwardDeg(start, end) < MIN_SPAN_DEG) end = normalizeAngle(start + MIN_SPAN_DEG);
	return drawn({ ...zones, [name]: { start, end } }, name);
}

export function moveEdge(zones: ChannelZones, name: ZoneName, edge: 'start' | 'end', angle: number): ChannelZones {
	if (name === 'precise') {
		// The sliver ends at the exit's start: only its start moves, and so its width.
		const width = forwardDeg(normalizeAngle(angle), zones.exit.start);
		return drawn({ ...zones, precise_width: Math.min(120, width > 240 ? 0 : width) }, 'precise');
	}
	const span = zones[name];
	return withSpan(zones, name, edge === 'start' ? { start: angle, end: span.end } : { start: span.start, end: angle });
}

export function moveZone(zones: ChannelZones, name: ZoneName, byDeg: number): ChannelZones {
	if (name === 'precise') return moveZone(zones, 'exit', byDeg);
	const span = zones[name];
	return withSpan(zones, name, { start: span.start + byDeg, end: span.end + byDeg });
}

export function widen(zones: ChannelZones, name: ZoneName, byDeg: number): ChannelZones {
	if (name === 'precise') {
		return drawn({ ...zones, precise_width: Math.max(0, Math.min(120, zones.precise_width + byDeg)) }, 'precise');
	}
	const span = zones[name];
	const width = Math.max(MIN_SPAN_DEG, spanWidth(span) + byDeg);
	const middle = spanMiddle(span);
	return withSpan(zones, name, { start: middle - width / 2, end: middle + width / 2 });
}

export function setRadius(
	zones: ChannelZones,
	which: 'inner_radius' | 'outer_radius' | 'exit_radius',
	radius: number
): ChannelZones {
	const next = { ...zones, [which]: Math.max(0, radius) };
	const offset = innerReach(zones) - zones.inner_radius;
	next.inner_radius = Math.max(0, Math.min(next.inner_radius, next.outer_radius - offset - MIN_RING_PX));
	const reach = next.inner_radius + offset;
	next.outer_radius = Math.max(reach + MIN_RING_PX, next.outer_radius);
	next.exit_radius = Math.min(next.outer_radius, Math.max(reach + MIN_RING_PX, next.exit_radius));
	return drawn(next, 'ring');
}

// The whole ring moved: the inner circle goes with it.
export function moveCenter(zones: ChannelZones, center: Point): ChannelZones {
	const innerCenter: Point | null = zones.inner_center
		? [zones.inner_center[0] + center[0] - zones.center[0], zones.inner_center[1] + center[1] - zones.center[1]]
		: null;
	return drawn({ ...zones, center, inner_center: innerCenter }, 'ring');
}

// The inner circle alone moved, never so far that the center leaves it.
export function moveHub(zones: ChannelZones, point: Point): ChannelZones {
	let [dx, dy] = [point[0] - zones.center[0], point[1] - zones.center[1]];
	const most = MAX_INNER_OFFSET * zones.inner_radius;
	const off = Math.hypot(dx, dy);
	if (off > most) [dx, dy] = [(dx * most) / off, (dy * most) / off];
	return drawn({ ...zones, inner_center: [zones.center[0] + dx, zones.center[1] + dy] }, 'ring');
}

export function setLocked(zones: ChannelZones, part: Part, locked: boolean): ChannelZones {
	const others = zones.locked.filter((p) => p !== part);
	return { ...zones, locked: locked ? [...others, part] : others };
}

export function sameZones(a: ChannelZones | null, b: ChannelZones | null): boolean {
	return JSON.stringify(a) === JSON.stringify(b);
}
