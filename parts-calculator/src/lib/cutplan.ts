// Bar-stock cut optimisation for the aluminium framing. Pure functions — given a
// list of pieces (length + quantity), a stock length, and a saw kerf, pack the
// pieces into as few bars as possible (or into easy same-length bundles).

export type Piece = { letter: string; len: number; qty: number };
export type Unit = { letter: string; len: number };
export type Bin = { items: Unit[]; consumed: number };
export type PlanGroup = { lens: number[]; count: number };

// millimetres → feet & sixteenths-of-an-inch, e.g. 320 → 1' 5/8"
export function ftin(mm: number): string {
	const gcd = (a: number, b: number): number => (b ? gcd(b, a % b) : a);
	let t = Math.round((mm / 25.4) * 16);
	const s = t < 0 ? '-' : '';
	t = Math.abs(t);
	const f = Math.floor(t / 192);
	const rem = t % 192;
	const inch = Math.floor(rem / 16);
	const fr = rem % 16;
	const p: string[] = [];
	if (f) p.push(f + "'");
	if (fr) {
		const g = gcd(fr, 16);
		p.push((inch ? inch + ' ' : '') + fr / g + '/' + 16 / g + '"');
	} else {
		p.push(inch + '"');
	}
	return s + p.join(' ');
}

export function expand(pieces: Piece[]): Unit[] {
	const u: Unit[] = [];
	for (const p of pieces) for (let i = 0; i < (p.qty || 0); i++) u.push({ letter: p.letter, len: p.len });
	return u;
}

function packGreedy(units: Unit[], usable: number, kerf: number, strat: 'ffd' | 'bfd'): Bin[] {
	const order = [...units].sort((a, b) => b.len - a.len);
	const bins: Bin[] = [];
	for (const u of order) {
		let cand = -1;
		let best: number | null = null;
		for (let i = 0; i < bins.length; i++) {
			const b = bins[i];
			const ex = u.len + (b.items.length ? kerf : 0);
			if (b.consumed + ex <= usable + 1e-6) {
				if (strat === 'ffd') {
					cand = i;
					break;
				}
				const rem = usable - (b.consumed + ex);
				if (best === null || rem < best) {
					best = rem;
					cand = i;
				}
			}
		}
		if (cand >= 0) {
			const b = bins[cand];
			b.consumed += u.len + (b.items.length ? kerf : 0);
			b.items.push(u);
		} else {
			bins.push({ items: [u], consumed: u.len });
		}
	}
	return bins;
}

// least-waste: try first-fit and best-fit decreasing, keep the better result
export function packOptimal(units: Unit[], usable: number, kerf: number): Bin[] {
	const a = packGreedy(units, usable, kerf, 'ffd');
	const b = packGreedy(units, usable, kerf, 'bfd');
	const waste = (bn: Bin[]) => bn.reduce((s, x) => s + (usable - x.consumed), 0);
	if (b.length < a.length) return b;
	if (a.length < b.length) return a;
	return waste(a) <= waste(b) ? a : b;
}

// easy bundles: one length per bar, packed as many as fit — simplest to cut
export function packBundle(units: Unit[], usable: number, kerf: number): Bin[] {
	const byLen: Record<string, Unit[]> = {};
	for (const u of units) {
		const k = u.len.toFixed(3);
		(byLen[k] = byLen[k] || []).push(u);
	}
	const bins: Bin[] = [];
	for (const k in byLen) {
		const g = byLen[k];
		const L = g[0].len;
		const per = Math.max(1, Math.floor((usable + kerf) / (L + kerf)));
		for (let i = 0; i < g.length; i += per) {
			const c = g.slice(i, i + per);
			bins.push({ items: c, consumed: c.reduce((s, _, idx) => s + L + (idx ? kerf : 0), 0) });
		}
	}
	return bins;
}

// collapse identical bars (same multiset of lengths) into groups for display
export function planGroups(bins: Bin[]): PlanGroup[] {
	const map = new Map<string, PlanGroup>();
	for (const b of bins) {
		const lens = b.items.map((i) => i.len).sort((x, y) => y - x);
		const key = lens.map((l) => l.toFixed(3)).join('|');
		if (!map.has(key)) map.set(key, { lens, count: 0 });
		map.get(key)!.count++;
	}
	return [...map.values()].sort(
		(a, b) => b.count - a.count || b.lens.reduce((s, x) => s + x, 0) - a.lens.reduce((s, x) => s + x, 0)
	);
}
