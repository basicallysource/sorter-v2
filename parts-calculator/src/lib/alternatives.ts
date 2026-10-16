// Whole-assembly alternatives: one slot in the machine that can be built either
// of two ways (today, the Orange Pi housing for the Orange Pi 5, or the one for
// the 5 Pro, Max and Ultra). The catalog carries both. The default one is on its
// parent's line and counts; the other is an `optional` line, which resolves to
// zero everywhere, and its parts have no quantity. Choosing the other one swaps
// the two at load: the lines trade their `optional` flag and the parts trade
// their quantities, so every total, list, tree and download below agrees without
// each of them having to know about the choice.
//
// The choice is read once, when the page loads, so changing it reloads the page.
import { browser } from '$app/environment';

export type AlternativeOption = { id: string; label: string; assembly: string };
export type Alternative = {
	id: string;
	label: string;
	/** The assembly whose lines hold one line per option. */
	parent: string;
	options: AlternativeOption[];
};

export const ALTERNATIVES: Alternative[] = [
	{
		id: 'orange-pi-board',
		label: 'Orange Pi board',
		parent: 'electronics',
		options: [
			{ id: 'orange-pi-5', label: 'Orange Pi 5', assembly: 'orange-pi-mount' },
			{ id: 'orange-pi-pro', label: 'Orange Pi 5 Pro, Max or Ultra', assembly: 'orange-pi-pro-housing' }
		]
	}
];

const KEY = 'sorter-alternatives-v1';

/** The option id chosen for each alternative; the first option is the default. */
export function selectedAlternatives(): Record<string, string> {
	const out: Record<string, string> = {};
	let saved: Record<string, string> = {};
	if (browser) {
		try {
			saved = JSON.parse(localStorage.getItem(KEY) ?? '{}') ?? {};
		} catch {
			/* ignore */
		}
	}
	for (const a of ALTERNATIVES) {
		out[a.id] = a.options.some((o) => o.id === saved[a.id]) ? saved[a.id] : a.options[0].id;
	}
	return out;
}

export function chooseAlternative(id: string, option: string): void {
	if (!browser) return;
	const next = { ...selectedAlternatives(), [id]: option };
	localStorage.setItem(KEY, JSON.stringify(next));
	location.reload();
}

type LineLike = { part?: string; assembly?: string; qty: unknown; optional?: boolean };
type AssemblyLike = { id: string; lines?: LineLike[] };
type PartLike = { id: string; quantities: Record<string, number> };

/** Apply the choices to copies of the catalog's assemblies and parts. With every
 *  alternative on its default the inputs come back untouched. */
export function applyAlternatives<A extends AssemblyLike, P extends PartLike>(
	assemblies: A[],
	parts: P[],
	selected: Record<string, string>
): { assemblies: A[]; parts: P[] } {
	const byId = new Map(assemblies.map((a) => [a.id, a]));
	const partMap = new Map(parts.map((p) => [p.id, p]));
	let outAssemblies = assemblies;
	let outParts = parts;
	for (const alt of ALTERNATIVES) {
		const chosen = alt.options.find((o) => o.id === selected[alt.id]) ?? alt.options[0];
		if (chosen === alt.options[0]) continue;
		const sections = Object.keys(
			(byId.get(alt.options[0].assembly)?.lines ?? [])
				.map((l) => (l.part ? partMap.get(l.part) : undefined))
				.find((p) => p && Object.keys(p.quantities).length)?.quantities ?? {}
		);
		const section = sections[0];
		const optionAssemblies = new Set(alt.options.map((o) => o.assembly));
		const swapped = new Map<string, P>();
		for (const o of alt.options) {
			const live = o === chosen;
			for (const line of byId.get(o.assembly)?.lines ?? []) {
				const part = line.part ? partMap.get(line.part) : undefined;
				if (!part) continue;
				// Hardware is not in `parts`, so only printed parts get here; the rest is counted off the tree.
				if (live && section && typeof line.qty === 'number') {
					swapped.set(part.id, { ...part, quantities: { ...part.quantities, [section]: line.qty } });
				} else if (!live && Object.keys(part.quantities).length) {
					swapped.set(part.id, { ...part, quantities: {} });
				}
			}
		}
		outParts = outParts.map((p) => swapped.get(p.id) ?? p);
		outAssemblies = outAssemblies.map((a) =>
			a.id !== alt.parent
				? a
				: {
						...a,
						lines: (a.lines ?? []).map((l) =>
							l.assembly && optionAssemblies.has(l.assembly)
								? { ...l, optional: l.assembly !== chosen.assembly }
								: l
						)
					}
		);
	}
	return { assemblies: outAssemblies, parts: outParts };
}
