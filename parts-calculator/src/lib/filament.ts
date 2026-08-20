/**
 * Filament math. Everything downstream of `grams` comes from the slicer
 * (slicer/filament.py) — this module only multiplies by quantities and groups
 * by color. No estimation happens here.
 */
import { LASER_CUT_PARTS, type LaserCutPart } from './lasercut';
import raw from '$lib/data/parts.generated.json';
import platesRaw from '$lib/data/plates.generated.json';
import { getBambuColor, type BambuColor } from '$lib/bambu-colors';

export type PlatePart = { name: string; count: number; part_id: string | null };
export type Plate = { id: string; name: string; download: string; thumbs: string[]; parts: PlatePart[] };
export const PLATES = platesRaw as Plate[];
const _platesByPart = new Map<string, Plate[]>();
for (const pl of PLATES)
	for (const pp of pl.parts)
		if (pp.part_id) (_platesByPart.get(pp.part_id) ?? _platesByPart.set(pp.part_id, []).get(pp.part_id)!).push(pl);
export function platesForPart(id: string): Plate[] {
	return _platesByPart.get(id) ?? [];
}

export type Section = {
	id: string;
	name: string;
	scales_with_layers: boolean;
	experimental?: boolean; // early / subject to heavy change — surfaced with a warning
	experimental_note?: string | null;
};
export type ChangePriority = `P${number}`;
export type ChangeTargetKind = 'parts' | 'assemblies' | 'sections' | 'lasercut' | 'hardware';
export type PlannedChange = {
	id: string;
	name: string;
	priority: ChangePriority;
	description: string;
	condition?: 'working' | 'broken';
	status?: 'planned' | 'complete';
	completed_at?: string;
	images?: { url: string; alt: string; caption?: string }[];
	targets: Partial<Record<ChangeTargetKind, string[]>>;
};
export type ColorRoleDef = { id: string; name: string; default: string };
export type Folder = { id: string; name: string; description?: string };

/** One BOM line of an assembly: a child part or sub-assembly with a quantity.
 *  qty 'per-layer' multiplies by the total configured layer count;
 *  'middle-layers' by (count − 2) — the layers between the two interfaces. */
export type AssemblyLine = {
	part?: string;
	assembly?: string;
	qty: number | 'per-layer' | 'middle-layers';
};

/** How an assembly's lines are physically joined. This belongs to the joint —
 *  the assembly — not to either member, the same rule the screws follow: a Pico
 *  isn't "a part that requires soldering", it's a part that gets soldered *to
 *  headers*. Buying either one alone implies no iron. */
export type JoinMethod = 'solder' | 'crimp' | 'glue' | 'press' | 'self-tap' | 'friction';
export type Joining = { method: JoinMethod; note?: string };

/** Human labels for the join methods, for badges and prose. */
export const JOIN_LABELS: Record<JoinMethod, string> = {
	solder: 'Soldering',
	crimp: 'Crimping',
	glue: 'Gluing',
	press: 'Press fit',
	// a screw cutting its own thread in printed plastic — no insert, no nut
	'self-tap': 'Self-tapping',
	// held by clamping force alone, e.g. a screw jammed in an extrusion slot
	friction: 'Friction'
};

/** Assemblies double as (a) legacy flat groupings the parts list rolls up under
 *  and (b) nodes of the experimental machine tree (when they carry `lines`).
 *  status: 'stub' = placeholder with nothing inside yet, 'partial' = some lines
 *  filled in but not everything the real assembly contains. */
export type Assembly = {
	id: string;
	name: string;
	description: string;
	docs?: string; // path on the docs site to the full assembly guide, e.g. /hardware/assembly/...
	section?: string; // places an empty/stub assembly in the legacy section list
	status?: 'stub' | 'partial';
	joining?: Joining[]; // work needed to make these lines into one unit
	lines?: AssemblyLine[];
};

/** The documentation site. An assembly's `docs` is a path on it, never a full
 *  URL, so the two stay linkable if the host ever moves. */
export const DOCS_BASE = 'https://docs.basically.website';

/** Absolute URL of an assembly's write-up on the docs site, or null when that
 *  assembly has no page there yet. */
export function docsUrl(a: Assembly): string | null {
	return a.docs ? DOCS_BASE + a.docs : null;
}

/** Hardware committed to a single physical part (heat inserts, press-fit
 *  bearings). Scales automatically with the part count. */
export type Requirement = { part: string; qty: number };

export type Vendor = {
	region: string;
	vendor?: string;
	url: string; // the plain listing, no referral tag
	affiliate_url?: string; // same listing with the project's Amazon tag
	price?: number;
	currency?: string; // absent = USD
	pack_qty?: number;
	as_of?: string;
	note?: string;
};

/** A group of hardware that looks alike, sharing one product photo. `match` is
 *  any subset of a part's `cots` block, so a family can be drawn as broadly as
 *  "every screw" or as narrowly as "M3 countersunk" — the most specific match
 *  wins. A photo of an M3 countersunk screw is a photo of an M5 one; what
 *  differs is the length, which the row labels over the image. */
export type Family = {
	id: string;
	name: string;
	match: Record<string, string | number>;
	image: string | null;
};

/** Thread size gets a colour so an M3 and an M5 don't read alike in a product
 *  photo, where they look near identical. Deliberately a small fixed set — if a
 *  size isn't here it simply gets no icon rather than an invented colour. */
export const SIZE_COLORS: Record<string, string> = {
	M3: '#2f6fd0', // blue
	M4: '#b8791b', // amber
	M5: '#7a4ec2', // violet
	M6: '#2c8a6b' // green
};

/** Stock material — bought as a length and cut down. Assembly lines count the
 *  *pieces* a build consumes; `pieces_per_unit` converts that to lengths to buy. */
export type Stock = {
	unit_length_mm: number;
	cut_length_mm: number;
	pieces_per_unit: number;
	unit_label: string; // "4 ft (1.22 m) length"
	piece_label: string; // "~1 ft (305 mm) piece"
};

/** A COTS (off-the-shelf) part: no STL, carries sourcing instead.
 *  sheet_qty/sheet_qty_text are transitional hand counts from the BOM sheet,
 *  kept until each part is placed as requires/lines in the assembly tree. */
export type Hardware = {
	id: string;
	kind: 'cots';
	cots?: { type: string; size?: string; variant?: string; length_mm?: number } | null;
	name: string;
	category?: string | null;
	description: string;
	note?: string | null;
	created_at: string;
	updated_at: string;
	attributes: { label: string; value: string }[];
	sheet_qty?: { per_machine?: number; per_layer?: number } | null;
	sheet_qty_text?: string | null;
	stock?: Stock | null; // set when the part is cut from a bought length
	sourcing?: { vendors: Vendor[] } | null;
	image: string | null; // content-addressed bucket URL
	// Marks a part that has an interchangeable alternative (e.g. socket vs button
	// head). `true` = a bare "Alternative" tag; a string names the alternative.
	alternative?: string | boolean | null;
};

/** A part's color is exactly one of these shapes. `by_section` lets a part that
 *  lives in multiple sections resolve a different color per section. */
export type ColorSpec =
	| { role: string }
	| { fixed: string }
	| { split: { color: string; qty: number }[] }
	| { by_section: Record<string, ColorSpec> }
	| { any: true };

/** One entry in a part archetype's version history. `commit` ties the version to
 *  a real git commit (null = pending an upcoming clean commit). OnShape links live
 *  at the version level: `onshape_doc` is the live document, `onshape_version` the
 *  immutable OnShape version this STL was exported from. */
export type PartVersion = {
	version: string;
	date: string;
	message: string;
	commit: string | null;
	onshape_doc?: string | null;
	onshape_version?: string | null;
	// archived assets for this version (old geometry pulled from git); the current
	// version reuses the live part asset. grams may be null if it couldn't slice.
	stl?: string;
	render?: string;
	grams?: number | null;
};

export type Part = {
	id: string;
	name: string;
	aliases?: string[]; // alternate shop/CAD names; canonical id and display name stay stable
	quantities: Record<string, number>; // category id -> count per ONE instance of that category
	assembly: string | null;
	folder?: string | null; // display-only collapsible grouping; carries no BOM semantics
	variant_group?: string | null; // parts in a group are alternatives chosen per layer
	variant_name?: string | null;
	description: string;
	version: string;
	created_at: string;
	updated_at: string;
	versions?: PartVersion[]; // archetype history, newest last
	attributes?: { label: string; value: string }[]; // variant characteristics shown in the app
	grams: number; // total incl. any support
	support_grams: number; // the support portion of `grams`
	support_used: boolean; // slicer used support to slice this (may be auto-forced)
	support_intentional?: boolean; // the part *opts into* support in the manifest (vs. auto-forced)
	print_seconds: number;
	color: ColorSpec;
	optional: boolean;
	onshape?: string | null; // link to the source Onshape document, if known
	info?: string | null; // short note surfaced as an inline info popover
	low_tolerance?: boolean; // tight/precise fit — little tolerance for dimensional error, so a test print is worth doing
	low_tolerance_note?: string | null; // optional specifics for the low-tolerance warning
	// how the per-layer ('layer') quantity scales: every layer, all but the bottom,
	// or the bottom layer only (for bottom-layer-swapped parts like the foot cover)
	layer_scope?: 'all' | 'non-bottom' | 'bottom-only';
	requires?: Requirement[]; // hardware committed to this physical part
	stl: string;
	render: string;
};
export type Settings = {
	printer: string;
	process: string;
	filament: string;
	infill_density: string;
	infill_pattern: string;
	support_enabled: boolean;
	support_type: string;
	support_threshold_deg: number;
	density_g_cm3: number;
	cost_per_kg: number;
	commit_base_url?: string; // e.g. https://github.com/owner/repo/commit/
	all_parts_zip?: string; // content-addressed bucket URL for the every-part bundle
};

/** Full URL for a version's commit, or null when the commit isn't known yet. */
export function commitUrl(commit: string | null | undefined): string | null {
	const base = SETTINGS.commit_base_url;
	return commit && base ? `${base}${commit}` : null;
}

export const SETTINGS = raw.settings as Settings;
export const SECTIONS = raw.sections as Section[];
export const CHANGES = ((raw as Record<string, unknown>).changes ?? []) as PlannedChange[];
export const FOLDERS = ((raw as Record<string, unknown>).folders ?? []) as Folder[];
export const COLOR_ROLES = raw.color_roles as ColorRoleDef[];
export const ASSEMBLIES = (raw.assemblies ?? []) as Assembly[];
export const PARTS = raw.parts as unknown as Part[];
export function plannedChangesFor(kind: ChangeTargetKind, id: string): PlannedChange[] {
	return CHANGES.filter((change) => {
		if (change.status === 'complete') return false;
		if (change.targets[kind]?.includes(id)) return true;
		if (kind !== 'parts') return false;
		const part = PARTS.find((candidate) => candidate.id === id);
		return !!part && (change.targets.sections ?? []).some((section) => section in part.quantities);
	});
}
export const HARDWARE = ((raw as Record<string, unknown>).hardware ?? []) as Hardware[];
export const FAMILIES = ((raw as Record<string, unknown>).families ?? []) as Family[];
export const SPOOL_G = 1000;

const sectionById = new Map(SECTIONS.map((s) => [s.id, s]));
const assemblyById = new Map(ASSEMBLIES.map((a) => [a.id, a]));
const folderById = new Map(FOLDERS.map((folder) => [folder.id, folder]));
const partById = new Map(PARTS.map((p) => [p.id, p]));
const hardwareById = new Map(HARDWARE.map((h) => [h.id, h]));
const lasercutById = new Map(LASER_CUT_PARTS.map((p) => [p.id, p]));

// Reverse index: which assemblies list a given part/hardware id as a member.
// Lets a flat view (the hardware page) surface the joint a part belongs to
// without walking the tree from the root — most electronics aren't placed in
// the machine tree yet, but they already know what they go together with.
const assembliesByMember = new Map<string, Assembly[]>();
for (const a of ASSEMBLIES) {
	for (const line of a.lines ?? []) {
		if (!line.part) continue;
		const list = assembliesByMember.get(line.part);
		if (list) list.push(a);
		else assembliesByMember.set(line.part, [a]);
	}
}

/** Assemblies this part or hardware item is a member of. */
export function assembliesContaining(id: string): Assembly[] {
	return assembliesByMember.get(id) ?? [];
}

/** The narrowest family this part falls into, if any. Specificity is just how
 *  many `cots` keys the family pins, so "M3 countersunk" beats "any screw". */
export function familyFor(h: Hardware): Family | undefined {
	const cots = (h.cots ?? {}) as Record<string, string | number | undefined>;
	let best: Family | undefined;
	for (const f of FAMILIES) {
		const keys = Object.keys(f.match);
		if (!keys.every((k) => cots[k] === f.match[k])) continue;
		if (!best || keys.length > Object.keys(best.match).length) best = f;
	}
	return best;
}

/** What to show for a hardware item: its own photo if it has one, else its
 *  family's. A family photo stands for several lengths, so callers pair it with
 *  the length label — see `hardwareLengthLabel`. */
export function hardwareImage(h: Hardware): { src: string; shared: boolean } | null {
	if (h.image) return { src: h.image, shared: false };
	const fam = familyFor(h);
	return fam?.image ? { src: fam.image, shared: true } : null;
}

/** The one thing a shared family photo can't show. Null when there's no length
 *  to state (a nut, an insert) or it isn't known yet. */
export function hardwareLengthLabel(h: Hardware): string | null {
	const mm = h.cots?.length_mm;
	return mm ? `${mm}mm` : null;
}

/** One hop on the way down to a piece of hardware. `via` names the printed part
 *  the hardware is committed to, when it arrived through a part's `requires`
 *  rather than as a line of the assembly itself. */
export type TreeStep = { assembly: Assembly; qty: number };
export type UsagePath = { steps: TreeStep[]; via: Part | null; qty: number };

/** Every route from the machine root down to a piece of hardware, so a builder
 *  can answer "where does this actually go?" — and walk up from there. Depth is
 *  bounded by the tree (cycle-checked at author time), so this stays cheap. */
export function usagePaths(hardwareId: string, layers: number): UsagePath[] {
	const found: UsagePath[] = [];
	const walk = (id: string, trail: TreeStep[], mult: number) => {
		const asm = assemblyById.get(id);
		if (!asm) return;
		for (const line of asm.lines ?? []) {
			const q = lineQty(line, layers) * mult;
			if (line.assembly) {
				walk(line.assembly, [...trail, { assembly: asm, qty: mult }], q);
			} else if (line.part === hardwareId) {
				found.push({ steps: [...trail, { assembly: asm, qty: mult }], via: null, qty: q });
			} else if (line.part) {
				const part = partById.get(line.part);
				for (const r of part?.requires ?? []) {
					if (r.part !== hardwareId) continue;
					found.push({
						steps: [...trail, { assembly: asm, qty: mult }],
						via: part ?? null,
						qty: r.qty * q
					});
				}
			}
		}
	};
	walk('machine', [], 1);
	return found.sort((a, b) => b.qty - a.qty);
}

/** Laser-cut sheet parts still live in their own module (design doc §5.5 folds
 *  them into the manifest later), but assembly lines may already reference one
 *  by id — the plywood top plate bolts to the interface brackets. */
export function getLasercut(id: string): LaserCutPart | undefined {
	return lasercutById.get(id);
}

export function getPart(id: string): Part | undefined {
	return partById.get(id);
}
export function getHardware(id: string): Hardware | undefined {
	return hardwareById.get(id);
}

/** Resolve an assembly line's quantity. Total layer count n includes the top
 *  and bottom interface levels; 'middle-layers' is the n−2 between them. */
export function lineQty(line: AssemblyLine, layers: number): number {
	if (line.qty === 'per-layer') return layers;
	if (line.qty === 'middle-layers') return Math.max(0, layers - 2);
	return line.qty;
}

/** Sum the hardware reachable from an assembly, multiplied down the tree — the
 *  design doc's resolver, restricted to the hardware group. Hardware arrives two
 *  ways: committed to a printed part (`requires`), or listed directly as a line
 *  of the assembly, which is how a joint's own components are recorded.
 *  Returns hardware id -> total count. */
export function resolveHardwareTotals(root: string, layers: number): Map<string, number> {
	const acc = new Map<string, number>();
	const walk = (id: string, mult: number) => {
		for (const line of assemblyById.get(id)?.lines ?? []) {
			const q = lineQty(line, layers) * mult;
			if (line.assembly) walk(line.assembly, q);
			else if (line.part) {
				if (hardwareById.has(line.part)) {
					acc.set(line.part, (acc.get(line.part) ?? 0) + q);
					continue;
				}
				for (const r of partById.get(line.part)?.requires ?? []) {
					acc.set(r.part, (acc.get(r.part) ?? 0) + r.qty * q);
				}
			}
		}
	};
	walk(root, 1);
	return acc;
}

// ---------------------------------------------------------------- hardware pricing
// Shared by the hardware page, the assembly tab, and the hardware detail modal so
// the list, the cart, and the popup all price a part the same way. Kept here rather
// than duplicated per page — the sourcing math is the same wherever a part is shown.

/** Machine total for a part: tree-derived when placed, else the BOM sheet count.
 *  `treeTotals` is the resolver output for the machine at the current layer count. */
export function hardwareTotalQty(
	h: Hardware,
	treeTotals: Map<string, number>,
	layers: number
): number | null {
	const fromTree = treeTotals.get(h.id);
	if (fromTree != null) return fromTree;
	if (h.sheet_qty?.per_machine != null) return h.sheet_qty.per_machine;
	if (h.sheet_qty?.per_layer != null) return h.sheet_qty.per_layer * layers;
	return null;
}

/** Where a count came from — a hand count carries much less confidence than one
 *  summed out of the tree, and the difference is worth showing. */
export function hardwareQtySource(
	h: Hardware,
	treeTotals: Map<string, number>
): 'tree' | 'sheet' | null {
	if (treeTotals.has(h.id)) return 'tree';
	return h.sheet_qty?.per_machine != null || h.sheet_qty?.per_layer != null ? 'sheet' : null;
}

/** Quantity in the units a vendor actually sells. Stock material is tallied in
 *  cut pieces but bought as whole lengths, so four 1 ft pieces is one rod —
 *  every price and pack calculation has to go through here. */
export function buyUnits(h: Hardware, qty: number | null): number | null {
	if (qty == null) return null;
	return h.stock ? Math.ceil(qty / h.stock.pieces_per_unit) : qty;
}

/** Listings to buy — Amazon counts packs, not units. */
export function packsNeeded(v: Vendor, qty: number): number {
	return v.pack_qty ? Math.ceil(qty / v.pack_qty) : 1;
}

/** Buy cost at a vendor for a total quantity (pack math), USD vendors only. */
export function buyCost(v: Vendor, qty: number | null): number | null {
	if (v.price == null || v.currency === 'EUR') return null;
	if (qty == null) return null;
	return packsNeeded(v, qty) * v.price;
}

/** Cheapest US vendor with a price, which is what the cart and totals use. */
export function bestUsVendor(h: Hardware): Vendor | null {
	const priced = (h.sourcing?.vendors ?? []).filter(
		(v) => v.region === 'US' && v.price != null && v.currency !== 'EUR'
	);
	if (!priced.length) return null;
	return priced.reduce((a, b) => (a.price! <= b.price! ? a : b));
}

/** Vendor price formatted in its own currency, or null when none is recorded. */
export function fmtPrice(v: Vendor): string | null {
	return v.price == null
		? null
		: v.currency === 'EUR'
			? `€${v.price.toFixed(2)}`
			: `$${v.price.toFixed(2)}`;
}

export function categoryMultiplier(categoryId: string, layers: number): number {
	return sectionById.get(categoryId)?.scales_with_layers ? layers : 1;
}

/** Layer multiplier for a part in a category, honoring its `layer_scope`.
 *  Distribution-frame ('layer') parts can apply to all layers, all but the
 *  bottom (standard brackets), or the bottom layer only (the foot cover). */
export function effectiveMult(part: Part, categoryId: string, layers: number): number {
	if (categoryId === 'layer') {
		if (part.layer_scope === 'non-bottom') return Math.max(0, layers - 1);
		if (part.layer_scope === 'bottom-only') return layers >= 1 ? 1 : 0;
	}
	return categoryMultiplier(categoryId, layers);
}

export function getAssembly(id: string | null): Assembly | undefined {
	return id ? assemblyById.get(id) : undefined;
}

/** Assembly descriptions name a fastener as `[[hw:<id>]]` rather than spelling
 *  out "M5×16", so a mention in prose and the row you actually buy from are the
 *  same thing: same parts-list name, same head symbol, same thread colour, same
 *  "A" tag. */
const HW_REF = /\[\[hw:([a-z0-9-]+)\]\]/g;

export type DescriptionSegment =
	| { kind: 'text'; text: string }
	| { kind: 'hw'; hw: Hardware };

/** A description split into plain runs and the hardware it names, in order. */
export function descriptionSegments(text: string): DescriptionSegment[] {
	const out: DescriptionSegment[] = [];
	let cut = 0;
	for (const m of text.matchAll(HW_REF)) {
		if (m.index > cut) out.push({ kind: 'text', text: text.slice(cut, m.index) });
		const hw = getHardware(m[1]);
		// An id that resolves to nothing stays on the page as its raw token. The
		// slicer rejects those before they ship, and a token that vanished
		// silently would leave a sentence missing its subject with nothing to see.
		out.push(hw ? { kind: 'hw', hw } : { kind: 'text', text: m[0] });
		cut = m.index + m[0].length;
	}
	if (cut < text.length) out.push({ kind: 'text', text: text.slice(cut) });
	return out;
}

/** The same text flattened to names, for the places that can only hold a plain
 *  string — a `title` tooltip, a CSV cell. */
export function plainDescription(text: string): string {
	return text.replace(HW_REF, (raw, id: string) => getHardware(id)?.name ?? raw);
}

export function getFolder(id: string | null): Folder | undefined {
	return id ? folderById.get(id) : undefined;
}

/** The part's current OnShape links, taken from its latest version (a part-level
 *  `onshape` link is honored as a legacy document fallback). */
export function partOnshape(part: Part): { doc: string | null; version: string | null } {
	const v = part.versions?.[part.versions.length - 1];
	return {
		doc: v?.onshape_doc ?? part.onshape ?? null,
		version: v?.onshape_version ?? null
	};
}

/** Count of this part within one instance of a given category. */
export function sectionQty(part: Part, sectionId: string): number {
	return part.quantities[sectionId] ?? 0;
}

/** Total count of this part across a whole machine. */
export function machineQty(part: Part, layers: number): number {
	let n = 0;
	for (const [cat, qty] of Object.entries(part.quantities)) {
		n += qty * effectiveMult(part, cat, layers);
	}
	return n;
}

/** Count to show/charge for a part in a given section, honoring variant overrides. */
export function displayCount(
	part: Part,
	sectionId: string,
	layers: number,
	variantCount: (id: string) => number | null
): number {
	const vc = variantCount(part.id);
	if (vc !== null) return vc; // variant parts (e.g. funnels) are counted per layer-choice
	return sectionQty(part, sectionId) * effectiveMult(part, sectionId, layers);
}

/** Resolve a `by_section` color to the spec for one section (falls back to the
 *  first section's spec when the section isn't listed / isn't given). */
function resolveColor(c: ColorSpec, sectionId?: string): Exclude<ColorSpec, { by_section: unknown }> {
	if ('by_section' in c) {
		const sub = (sectionId && c.by_section[sectionId]) || Object.values(c.by_section)[0];
		return resolveColor(sub, sectionId);
	}
	return c;
}

/** Per-color unit breakdown of `catQty` pieces of a part (1 category instance). */
function colorUnits(
	part: Part,
	catQty: number,
	roleColors: Record<string, string>,
	sectionId?: string
): { colorId: string | null; count: number }[] {
	const c = resolveColor(part.color, sectionId);
	if ('split' in c) return c.split.map((s) => ({ colorId: s.color, count: s.qty }));
	if ('fixed' in c) return [{ colorId: c.fixed, count: catQty }];
	if ('role' in c) return [{ colorId: roleColors[c.role] ?? null, count: catQty }];
	return [{ colorId: null, count: catQty }];
}

/** Machine-wide per-color breakdown, summed across every section the part
 *  appears in. A part whose color is `split`, or `by_section` with different
 *  colors per section, yields several entries — the stator is 3 charcoal in the
 *  feeder and 1 ash gray in the classification channel. Everything else yields
 *  one. `sections` names only the sections contributing THAT color.
 *
 *  Zero-count entries (a section whose multiplier is 0 at this layer count) are
 *  dropped unless they're all that's left, so a part never vanishes entirely. */
export function machineColorUnits(
	part: Part,
	layers: number,
	roleColors: Record<string, string>
): { colorId: string | null; count: number; sections: string[] }[] {
	const acc = new Map<string, { colorId: string | null; count: number; sections: string[] }>();
	for (const [cat, qty] of Object.entries(part.quantities)) {
		const mult = effectiveMult(part, cat, layers);
		for (const u of colorUnits(part, qty, roleColors, cat)) {
			const key = u.colorId ?? '__any__';
			const e = acc.get(key) ?? { colorId: u.colorId, count: 0, sections: [] };
			e.count += u.count * mult;
			if (!e.sections.includes(cat)) e.sections.push(cat);
			acc.set(key, e);
		}
	}
	const units = [...acc.values()];
	const live = units.filter((u) => u.count > 0);
	return live.length ? live : units.slice(0, 1);
}

/** The part's primary resolved color id (for the 3D preview default). */
export function primaryColorId(part: Part, roleColors: Record<string, string>): string | null {
	const c = resolveColor(part.color);
	if ('split' in c) return c.split[0]?.color ?? null;
	if ('fixed' in c) return c.fixed;
	if ('role' in c) return roleColors[c.role] ?? null;
	return null;
}

/** Swatches to display for a part within a section (resolved against roles). */
export function partSwatches(
	part: Part,
	sectionId: string,
	roleColors: Record<string, string>
): { color: BambuColor | null; qty: number }[] {
	return colorUnits(part, sectionQty(part, sectionId), roleColors, sectionId).map((u) => ({
		color: u.colorId ? getBambuColor(u.colorId) : null,
		qty: u.count
	}));
}

// Bambu Lab PLA Matte, with-spool pricing (same tiers as Basic). Bulk discount keys off the TOTAL roll
// count in the order (mix-and-match across colors). From the Bambu US store.
export const STORE_URL = 'https://us.store.bambulab.com/collections/filament-bulk-sale';
export const PRICE_TIERS = [
	{ minSpools: 6, pricePerSpool: 16.99 },
	{ minSpools: 4, pricePerSpool: 17.99 },
	{ minSpools: 1, pricePerSpool: 24.99 }
];
export function pricePerSpool(totalSpools: number): number {
	return (PRICE_TIERS.find((t) => totalSpools >= t.minSpools) ?? PRICE_TIERS.at(-1)!).pricePerSpool;
}

export type BuyLine = {
	colorId: string | null;
	color: BambuColor | null;
	label: string;
	grams: number;
	spools: number;
	cost: number;
};

/** Grams counted for a part: total when its support is included, else object-only. */
export function effectiveGrams(part: Part, inclSupport: boolean): number {
	return inclSupport ? part.grams : part.grams - part.support_grams;
}

/** Group the SELECTED parts' filament by resolved color, with bulk-tier pricing.
 *  `inclSupport(id)` decides whether a part's support material counts.
 *  `surplusPct` adds a buffer (incidental parts / failed prints) before spool counts. */
export function buyList(
	layers: number,
	roleColors: Record<string, string>,
	isSelected: (id: string) => boolean,
	inclSupport: (id: string) => boolean,
	variantCount: (id: string) => number | null,
	surplusPct = 0
): {
	lines: BuyLine[];
	totalGrams: number;
	totalSpools: number;
	totalCost: number;
	perSpool: number;
} {
	const byColor = new Map<string, number>();
	for (const part of PARTS) {
		if (!isSelected(part.id)) continue;
		const each = effectiveGrams(part, inclSupport(part.id));
		const vc = variantCount(part.id);
		if (vc !== null) {
			// variant part (e.g. funnel): total machine count chosen per layer
			for (const u of colorUnits(part, vc, roleColors)) {
				const key = u.colorId ?? '__any__';
				byColor.set(key, (byColor.get(key) ?? 0) + each * u.count);
			}
			continue;
		}
		for (const [cat, qty] of Object.entries(part.quantities)) {
			const mult = effectiveMult(part, cat, layers);
			for (const u of colorUnits(part, qty, roleColors, cat)) {
				const key = u.colorId ?? '__any__';
				byColor.set(key, (byColor.get(key) ?? 0) + each * u.count * mult);
			}
		}
	}
	const buffer = 1 + surplusPct / 100;
	const rows = [...byColor.entries()].map(([key, raw]) => {
		const grams = raw * buffer;
		return { key, grams, spools: Math.max(1, Math.ceil(grams / SPOOL_G)) };
	});
	const totalSpools = rows.reduce((a, e) => a + e.spools, 0);
	const perSpool = pricePerSpool(totalSpools);
	const lines: BuyLine[] = rows
		.map((e) => {
			const colorId = e.key === '__any__' ? null : e.key;
			const color = colorId ? getBambuColor(colorId) : null;
			return {
				colorId,
				color,
				label: color ? color.name : 'Any color',
				grams: e.grams,
				spools: e.spools,
				cost: e.spools * perSpool
			};
		})
		.sort((a, b) => b.grams - a.grams);
	const totalGrams = rows.reduce((a, e) => a + e.grams, 0);
	return { lines, totalGrams, totalSpools, totalCost: totalSpools * perSpool, perSpool };
}

export function grams(n: number): string {
	return n >= 1000 ? `${(n / 1000).toFixed(2)} kg` : `${Math.round(n)} g`;
}
export function money(n: number): string {
	return `$${n.toFixed(2)}`;
}
/** Format an ISO date (YYYY-MM-DD) as e.g. "Jul 8, 2026". Empty in -> "". */
export function fmtDate(iso: string | undefined | null): string {
	if (!iso) return '';
	const [y, m, d] = iso.split('-').map(Number);
	if (!y || !m || !d) return iso;
	const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
	return `${months[m - 1]} ${d}, ${y}`;
}
export function duration(sec: number): string {
	const h = Math.floor(sec / 3600);
	const m = Math.round((sec % 3600) / 60);
	return h ? `${h}h ${m}m` : `${m}m`;
}
/** Longer-form for big totals: days + hours past 2 days, else h + m. */
export function durationLong(sec: number): string {
	const totalH = sec / 3600;
	if (totalH >= 48) {
		const d = Math.floor(totalH / 24);
		const h = Math.round(totalH - d * 24);
		return `${d}d ${h}h`;
	}
	return duration(sec);
}
