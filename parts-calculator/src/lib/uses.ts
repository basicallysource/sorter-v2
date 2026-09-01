/**
 * Where each printed part is actually used, and how many go there.
 *
 * A part is not a thing you print once. It is a thing you print N times because
 * it is needed in N places, and those places are what you tick on and off when
 * you decide what to put on a plate. This module turns the catalog into that
 * list: one `PartUse` per (part, assembly) pair, carrying the count for the
 * current layer configuration.
 *
 * Two sources have to be reconciled, because neither is complete on its own:
 *
 *   - `part.quantities` (section -> count) covers every part in the build and
 *     is what the totals have always been computed from. It is authoritative
 *     for HOW MANY.
 *   - the assembly tree's `lines` say WHERE, and are the only thing that knows
 *     a part is used in two different places. But the tree is still filling in:
 *     as of 2026-08-22 it reaches 73 of the 89 build parts, and for five more
 *     it reaches only some of the copies (frame-90deg-bracket is in both the
 *     `layer` and `interface` sections; the tree has only the layer ones).
 *
 * So the tree supplies the grouping, the sections supply the number, and
 * whatever the tree cannot account for becomes one explicit "not in the
 * assembly tree yet" use rather than quietly going missing. The invariant that
 * makes the UI safe to build on: **a part's uses always sum to exactly the
 * quantity the machine needs.** Nothing can hide in the gap.
 */
import {
	ASSEMBLIES,
	PARTS,
	getAssembly,
	lineQty,
	machineQty,
	type Part
} from './filament';

/** The id used for the bucket holding copies the assembly tree doesn't explain. */
export const UNTRACKED = '~untracked';

export type PartUse = {
	/** Stable across re-renders and safe as a persisted key. */
	key: string;
	partId: string;
	/** The assembly that lists this part, or null for the untracked bucket. */
	assemblyId: string | null;
	assemblyName: string;
	qty: number;
};

const useKey = (partId: string, assemblyId: string | null) =>
	`${partId}@${assemblyId ?? UNTRACKED}`;

/** Walk the machine tree, attributing each part to the assembly that directly lists
 *  it, multiplied by how many of that assembly the machine has. */
function treeCounts(layers: number): Map<string, Map<string, number>> {
	const out = new Map<string, Map<string, number>>();
	const seen = new Set<string>();
	function walk(assemblyId: string, mult: number) {
		// Guard against a cycle in authored data; a machine tree has none, but a
		// typo could make one and an infinite walk is a blank page.
		const guard = `${assemblyId}:${mult}`;
		if (seen.has(guard)) return;
		seen.add(guard);
		const asm = getAssembly(assemblyId);
		if (!asm) return;
		for (const line of asm.lines ?? []) {
			const n = lineQty(line, layers) * mult;
			if (line.assembly) {
				walk(line.assembly, n);
			} else if (line.part) {
				const per = out.get(line.part) ?? new Map<string, number>();
				per.set(assemblyId, (per.get(assemblyId) ?? 0) + n);
				out.set(line.part, per);
			}
		}
	}
	walk('machine', 1);
	return out;
}

/**
 * Every part's uses for this layer configuration, keyed by part id.
 *
 * `variantCount` is the page's per-layer override for parts whose count comes
 * from the funnel/bin size choices rather than from a fixed per-section count.
 * Parts with no sections at all (a candidate's parts, which are not in the
 * build) get no uses, which is what keeps them off the dashboard.
 */
export function buildUses(
	layers: number,
	variantCount: (id: string) => number | null
): Map<string, PartUse[]> {
	const tree = treeCounts(layers);
	const byPart = new Map<string, PartUse[]>();

	for (const part of PARTS) {
		if (!Object.keys(part.quantities).length) continue; // not in the build
		const needed = variantCount(part.id) ?? machineQty(part, layers);
		if (needed <= 0) continue;

		const uses: PartUse[] = [];
		let placed = 0;
		for (const [assemblyId, qty] of tree.get(part.id) ?? []) {
			// Never let the tree claim more copies than the machine needs; the
			// sections are the authority on the number.
			const take = Math.min(qty, needed - placed);
			if (take <= 0) break;
			uses.push({
				key: useKey(part.id, assemblyId),
				partId: part.id,
				assemblyId,
				assemblyName: getAssembly(assemblyId)?.name ?? assemblyId,
				qty: take
			});
			placed += take;
		}
		if (placed < needed) {
			uses.push({
				key: useKey(part.id, null),
				partId: part.id,
				assemblyId: null,
				assemblyName: 'Not in the assembly tree yet',
				qty: needed - placed
			});
		}
		byPart.set(part.id, uses);
	}
	return byPart;
}

/** Assemblies that appear as a use somewhere, in machine-tree order, so the
 *  by-assembly view lists them the way the tree walks them. */
export function assemblyOrder(): string[] {
	const order: string[] = [];
	const seen = new Set<string>();
	function walk(id: string) {
		if (seen.has(id)) return;
		seen.add(id);
		order.push(id);
		for (const line of getAssembly(id)?.lines ?? []) {
			if (line.assembly) walk(line.assembly);
		}
	}
	walk('machine');
	// anything authored but not reachable from `machine` still deserves a place
	for (const a of ASSEMBLIES) if (!seen.has(a.id)) order.push(a.id);
	return order;
}

/** Total copies of a part the machine needs — always the sum of its uses. */
export function defaultQty(uses: PartUse[] | undefined): number {
	return (uses ?? []).reduce((n, u) => n + u.qty, 0);
}

/** Which parts are used in more than one assembly — the marker in both views. */
export function sharedParts(byPart: Map<string, PartUse[]>): Set<string> {
	const shared = new Set<string>();
	for (const [id, uses] of byPart) if (uses.length > 1) shared.add(id);
	return shared;
}

export type { Part };
