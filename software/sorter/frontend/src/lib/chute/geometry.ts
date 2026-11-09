// Chute aiming geometry, mirroring the backend's canonical formula (chute.py):
//   bin_center = θ0 + section·(360/N) + (i + 0.5)·(W / K)
// Kept in one place so the calibration page and the per-size viz agree on
// exactly where the chute points and which bins it can physically reach.

export type ChuteGeometry = {
	numSections: number;
	sectionWidthDeg: number;
	firstSectionOffsetDeg: number;
};

export function binCenterAngle(
	geo: ChuteGeometry,
	section: number,
	bin: number,
	binCount: number
): number {
	const k = Math.max(1, binCount);
	const slot = geo.sectionWidthDeg / k;
	return geo.firstSectionOffsetDeg + section * (360 / Math.max(1, geo.numSections)) + (bin + 0.5) * slot;
}

export function normDeg(angle: number): number {
	return ((angle % 360) + 360) % 360;
}

// A chute with a travel limit turns over [0, maxAngle]; the wedge
// (maxAngle, 360) straddling home-zero is the single mechanical deadzone. A bin
// is reachable iff its midpoint, wrapped onto the circle, lands inside the
// travel window. This is what makes the model agnostic to whether home sits in
// a pillar or in the middle of a section: the deadzone simply eats whichever
// bins fall in it. A chute that turns without limit (maxAngle null) reaches
// every angle.
export function reachInfo(
	angle: number,
	maxAngleDeg: number | null
): { reachable: boolean; norm: number; reason: string | null } {
	const norm = normDeg(angle);
	if (maxAngleDeg === null || norm <= maxAngleDeg) return { reachable: true, norm, reason: null };
	const into = norm - maxAngleDeg;
	return {
		reachable: false,
		norm,
		reason: `${into.toFixed(1)}° into the no-go wedge: the chute would have to pass ${maxAngleDeg.toFixed(0)}° to reach it, but it hits the home stop first`
	};
}

