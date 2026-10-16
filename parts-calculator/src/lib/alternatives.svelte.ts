// Whole-assembly alternatives: one slot in the machine that can be built either
// of two ways (today, the Orange Pi housing for the Orange Pi 5, or the one for
// the 5 Pro, Max and Ultra). The catalog carries both. The default one is on its
// parent's line and counts; the other is an `optional` line, which resolves to
// zero everywhere, and its parts have no quantity. Choosing the other one swaps
// the two: the lines trade their `optional` flag and the parts trade their
// quantities, so every total, list, tree and download agrees without each of them
// having to know about the choice.
//
// The few catalog objects that trade are made reactive ($state) when the catalog
// is loaded, and choosing mutates them in place, so whatever reads them updates
// without a reload.
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

/** The alternative an assembly is one option of, if any. A page keys things it
 *  remembers about a row (open or closed) on this rather than on the assembly,
 *  so they survive switching the option. */
export function alternativeOf(assembly: string): string | undefined {
	return ALTERNATIVES.find((a) => a.options.some((o) => o.assembly === assembly))?.id;
}

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


type LineLike = { part?: string; assembly?: string; qty: unknown; optional?: boolean };
type AssemblyLike = { id: string; lines?: LineLike[] };
type PartLike = { id: string; quantities: Record<string, number> };

/** The choice per alternative, live: read it in a template or a $derived. */
export const alternativeStore = $state<{ selected: Record<string, string> }>({
	selected: selectedAlternatives()
});

type Slot = {
	alt: Alternative;
	section: string | undefined;
	/** per option: its printed parts (with their count and original quantities) */
	parts: Map<string, { part: PartLike; qty: number; own: Record<string, number> }[]>;
	/** the parent's line for each option's assembly */
	lines: Map<string, LineLike>;
};
const slots: Slot[] = [];

/** Make the parts and lines that trade places reactive, and apply the saved
 *  choice. Returns copies of the two lists holding the reactive objects; the
 *  catalog's own objects are not touched. */
export function bindAlternatives<A extends AssemblyLike, P extends PartLike>(
	assemblies: A[],
	parts: P[]
): { assemblies: A[]; parts: P[] } {
	const outAssemblies = [...assemblies];
	const outParts = [...parts];
	const partIndex = new Map(outParts.map((p, i) => [p.id, i]));
	const asmIndex = new Map(outAssemblies.map((a, i) => [a.id, i]));
	for (const alt of ALTERNATIVES) {
		const slot: Slot = { alt, section: undefined, parts: new Map(), lines: new Map() };
		for (const o of alt.options) {
			const asm = outAssemblies[asmIndex.get(o.assembly) ?? -1];
			const list: { part: PartLike; qty: number; own: Record<string, number> }[] = [];
			for (const line of asm?.lines ?? []) {
				const i = line.part ? partIndex.get(line.part) : undefined;
				// Hardware is not in `parts`, so only printed parts get here; the rest is counted off the tree.
				if (i === undefined || typeof line.qty !== 'number') continue;
				const part = $state({ ...outParts[i], quantities: { ...outParts[i].quantities } });
				outParts[i] = part;
				const own = { ...part.quantities };
				if (!slot.section) slot.section = Object.keys(own)[0];
				list.push({ part, qty: line.qty, own });
			}
			slot.parts.set(o.id, list);
		}
		const parentAt = asmIndex.get(alt.parent);
		const parent = parentAt === undefined ? undefined : outAssemblies[parentAt];
		if (parent && parentAt !== undefined) {
			const lines = (parent.lines ?? []).map((l) => {
				const o = alt.options.find((x) => x.assembly === l.assembly);
				if (!o) return l;
				const live = $state({ ...l });
				slot.lines.set(o.id, live);
				return live;
			});
			outAssemblies[parentAt] = { ...parent, lines };
		}
		slots.push(slot);
		applyChoice(slot, alternativeStore.selected[alt.id]);
	}
	return { assemblies: outAssemblies, parts: outParts };
}

function applyChoice(slot: Slot, option: string) {
	const chosen = slot.alt.options.find((o) => o.id === option) ?? slot.alt.options[0];
	for (const o of slot.alt.options) {
		const live = o.id === chosen.id;
		for (const { part, qty, own } of slot.parts.get(o.id) ?? []) {
			part.quantities = live
				? Object.keys(own).length
					? { ...own }
					: slot.section
						? { [slot.section]: qty }
						: {}
				: {};
		}
		const line = slot.lines.get(o.id);
		if (line) line.optional = !live;
	}
}

export function chooseAlternative(id: string, option: string): void {
	const slot = slots.find((s) => s.alt.id === id);
	if (!slot || !slot.alt.options.some((o) => o.id === option)) return;
	alternativeStore.selected[id] = option;
	if (browser) localStorage.setItem(KEY, JSON.stringify({ ...alternativeStore.selected }));
	applyChoice(slot, option);
}

/** Back to the default option of every alternative ("Reset to default"). */
export function resetAlternatives(): void {
	for (const a of ALTERNATIVES) chooseAlternative(a.id, a.options[0].id);
}
