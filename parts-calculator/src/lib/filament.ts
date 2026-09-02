/**
 * Catalog data + filament math. Everything here reads the one generated file
 * (catalog.generated.json, written by catalog/generate.py) — this module only
 * multiplies by quantities and groups by color. No estimation happens here.
 */
import { LASER_CUT_PARTS, type LaserCutPart } from './lasercut';
import raw from '$lib/data/catalog.generated.json';
import { getBambuColor, type BambuColor } from '$lib/bambu-colors';

export type PlatePart = { name: string; count: number; part_id: string | null };
export type Plate = { id: string; name: string; download: string; thumbs: string[]; parts: PlatePart[] };
export const PLATES = ((raw as { plates?: Plate[] }).plates ?? []) as Plate[];
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
/** A picture of a thing beyond its render: an Onshape screenshot, a section
 *  view, a photo of it built. `url` is a pinned published URL (publish the file
 *  with scripts/publish_assets.py --upload); `alt` says what the picture shows. */
export type CatalogImage = { url: string; alt: string; caption?: string };
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
	images?: CatalogImage[];
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

/** A superseded structure of an assembly: its lines as they were, each member
 *  pinned to the uid it had then, so the box as built at that time reads back
 *  part by part. Written by stamp_versions.py at supersession. */
export type AssemblySnapshotLine = AssemblyLine & { uid?: string };
export type AssemblyVersion = {
	version: string;
	uid?: string;
	date: string;
	message: string;
	commit: string | null;
	breaking?: boolean; // required on entries since 2026-08-31 (VERSIONING.md)
	lines?: AssemblySnapshotLine[];
	images?: CatalogImage[];
};

/** A whole alternative bill of materials under test for an assembly -- its own
 *  uid, never counted, never deleted once listed (marked superseded/rejected). */
export type AssemblyCandidate = {
	uid: string;
	name?: string; // what the slot is called if this is adopted
	created_at: string;
	message: string;
	lines: AssemblyLine[];
	joining?: Joining[]; // how these lines become one unit, when it differs
	images?: CatalogImage[];
	superseded_by?: string | null;
	superseded_at?: string | null;
	rejected_at?: string | null;
};

/** Assemblies double as (a) legacy flat groupings the parts list rolls up under
 *  and (b) nodes of the experimental machine tree (when they carry `lines`). */
export type Assembly = {
	id: string;
	uid: string; // the current structure's id, minted like a part's
	version?: string; // bumps on an authored structural change, not a member rev
	versions?: AssemblyVersion[]; // newest last; superseded ones carry a line snapshot
	candidates?: AssemblyCandidate[]; // alternative BOMs under test, oldest first
	name: string;
	description: string;
	docs?: string; // path on the docs site to the full assembly guide, e.g. /hardware/assembly/...
	joining?: Joining[]; // work needed to make these lines into one unit
	lines?: AssemblyLine[];
	connections?: Connection[]; // the joints, as edges over this assembly's lines
	images?: CatalogImage[]; // beyond the members' renders: a photo of it built, a section view
};

/** A joint recorded as an edge over the assembly's own lines. `to` is the
 *  anchor side — where the fastener ends; `via` names the fastener line and
 *  is absent for fastenerless methods; `draft` marks an edge extracted from
 *  prose and not yet confirmed at the bench (scripts/check_connections.py). */
export type ConnectionMethod =
	| JoinMethod
	| 'thread'
	| 'insert'
	| 'nut'
	| 'tnut'
	| 'gravity';
/** ISO 10642 countersunk head heights by thread size. A countersunk screw's
 *  nominal length is measured over the head, and the head rides inside the
 *  countersink — so only nominal minus head actually travels the joint. */
const CSK_HEAD_MM: Record<string, number> = { M3: 1.7, M4: 2.3, M5: 2.8, M6: 3.3 };

/** How far a screw reaches through a joint: nominal length, less the head for
 *  countersunk screws. Null when the length isn't recorded. */
export function screwTravel(h: Hardware | null | undefined): number | null {
	const len = h?.cots?.length_mm;
	if (len == null) return null;
	return h?.cots?.variant === 'countersunk' ? len - (CSK_HEAD_MM[h.cots.size ?? ''] ?? 0) : len;
}

export type Connection = {
	from: string;
	to: string;
	via?: string;
	qty: number;
	method: ConnectionMethod;
	/** The fastener's travel through the `from` side before it reaches the
	 *  anchor, and the thread length waiting on the `to` side — measured, so
	 *  compatible screw lengths are computable instead of remembered. */
	through_mm?: number;
	thread_mm?: number;
	note?: string;
	draft?: boolean;
};

/** The documentation site. An assembly's `docs` is a path on it, never a full
 *  URL, so the two stay linkable if the host ever moves. */
export const DOCS_BASE = 'https://docs.basically.website';

/** Absolute URL of an engineering note: one permanent, unlisted page per
 *  minted id, written when something happened to a part that a version line
 *  cannot carry (why an export was replaced, what was measured, what was
 *  ruled out). Ids come from the same pool as part uids, so one never means
 *  two things. */
export function noteUrl(id: string): string {
	return `${DOCS_BASE}/n/${id}/`;
}

/** Absolute URL of an assembly's write-up on the docs site, or null when that
 *  assembly has no page there yet. */
export function docsUrl(a: Assembly): string | null {
	return a.docs ? DOCS_BASE + a.docs : null;
}

/** Fastener anchors committed to a single physical part before it joins
 *  anything — heat-set inserts, which a later joint's `insert` edge threads
 *  into. Scales automatically with the part count. Components that merely
 *  install into a part (a press-fit bearing) are NOT this: they are members
 *  of the assembly where the joint happens, connected by a `press` edge. */
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
/** An unresolved factual disagreement between merged parts catalogs (see the
 *  manifest's `merges`): each claim is one source's version of the disputed
 *  field. Kept as data on purpose and badged in the UI until someone settles
 *  it against the physical machine and deletes the entry in parts.json. */
export type CatalogConflict = {
	merge: string;
	field: string;
	claims: { source: string; value: unknown }[];
	note?: string | null;
};

/** A recorded catalog-merger event that conflicts point at via `merge`. */
export type CatalogMerge = { id: string; date: string; sources: string[]; note?: string };

export type Hardware = {
	id: string;
	uid: string; // minted like a printed part's, so one id scheme covers the machine
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
	image: string | null; // content-addressed published URL
	images?: CatalogImage[]; // extra pictures beyond the product photo
	// Marks a part that has an interchangeable alternative (e.g. socket vs button
	// head). `true` = a bare "Alternative" tag; a string names the alternative.
	alternative?: string | boolean | null;
	caption?: string | null; // small text under this part's docs parts-needed card
	docs_page?: string | null; // its docs-site detail page, when one exists
	conflicts?: CatalogConflict[] | null;
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
	uid?: string; // the id this version carried; the newest's is the part's own
	date: string;
	message: string;
	commit: string | null;
	breaking?: boolean; // required on entries since 2026-08-31 (VERSIONING.md)
	note?: string; // an engineering note's id, if this version has one
	onshape_doc?: string | null;
	onshape_version?: string | null;
	// archived assets for this version (old geometry pulled from git); the current
	// version reuses the live part asset. grams may be null if it couldn't slice.
	stl?: string;
	render?: string;
	grams?: number | null;
	images?: CatalogImage[];
};

/** A design revision under test for a part's slot: its own uid and pinned STL,
 *  sliced and rendered like a version, but never adopted (yet) and so with no
 *  version number. Superseded and rejected candidates stay listed so the uid
 *  engraved on a test print always resolves. */
export type PartCandidate = {
	uid: string;
	name?: string; // what the slot is called if this is adopted
	created_at: string;
	message: string;
	onshape_version?: string | null;
	images?: CatalogImage[];
	superseded_by?: string | null;
	superseded_at?: string | null;
	rejected_at?: string | null;
	stl: string;
	render?: string | null;
	grams?: number | null;
	print_seconds?: number | null;
	support_used?: boolean;
	stamped?: PartStamp[];
	note?: string; // an engineering note's id, if this candidate has one
};
/** A download with the uid recessed into one face (catalog/engrave.py). `face`
 *  names it ("bottom", "+x side", "angled face"); `center`, `normal` and
 *  `size` ([width, height] mm) locate the text in the STL's own coordinates so
 *  the viewer can paint its pocket and fly to it. The first of a list is the
 *  default: the face a stamp prints and hides best. */
export type PartStamp = {
	face: string;
	stl: string;
	normal: number[];
	center: number[];
	size: number[];
	cap: number; // text height, mm: 3.5, or 2.5 when nothing on the part takes 3.5
	depth: number; // pocket depth, mm: 0.6, or 0.4 on a sheet too thin for it
	note?: string; // "smaller text", "shallow pocket" -- why this one is not the usual
	// set when the face is a cylindrical or conical wall: the surface of
	// revolution it sits on (axis, a point on it, radius there, radius change
	// per mm along the axis, +1 convex / -1 bore), so depth is measured
	// radially rather than against a tangent plane
	surface?: { axis: number[]; point: number[]; r0: number; slope: number; sign: number };
};

export type Part = {
	id: string;
	uid: string; // the current version's id -- what a print is engraved with
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
	note?: string; // an engineering note's id, when the part itself has one
	versions?: PartVersion[]; // archetype history, newest last
	candidates?: PartCandidate[]; // revisions under test for this slot, oldest first
	images?: CatalogImage[]; // extra pictures beyond the render
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
	caption?: string | null; // small text under this part's docs parts-needed card
	docs_page?: string | null; // its docs-site detail page, when one exists
	conflicts?: CatalogConflict[] | null;
	stl: string;
	render: string;
	stamped?: PartStamp[]; // uid-stamped downloads, best face first; empty when the uid fits nowhere
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
	all_parts_zip?: string; // content-addressed URL for the every-part bundle (each part's default stamped variant)
	all_parts_plain_zip?: string; // the same parts unstamped
};

/** The download for a part honouring the "engrave version id" choice: its
 *  default stamped variant when on and one exists, else the plain master. */
export function partDownload(p: Part, engrave: boolean): string {
	return (engrave && p.stamped?.[0]?.stl) || p.stl;
}

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
/** A blessed moment of a node's whole subtree — resolved against history like
 *  a timeline point. 'stable' means the build as of that moment is known good;
 *  'golden' adds the forward promise that future revisions must stay
 *  compatible with it. Appended only by a human decision. */
export type CatalogTag = {
	name: string;
	node: string;
	stability: 'golden' | 'stable' | 'experimental';
	date: string;
	commit?: string | null;
	message?: string;
};
export const TAGS = (((raw as Record<string, unknown>).tags ?? []) as CatalogTag[]);

export const ASSEMBLIES = (raw.assemblies ?? []) as Assembly[];
export const PARTS = raw.parts as unknown as Part[];
export const MERGES = ((raw as Record<string, unknown>).merges ?? []) as CatalogMerge[];
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

/** What a uid names. A uid is the 4-character id every part, version,
 *  candidate and assembly carries (catalog/mint_uid.py) -- the thing recessed
 *  into a print -- and once minted it never leaves the catalog, so anything
 *  ever stamped resolves here, current or not. */
export type UidMatch =
	| { kind: 'part'; part: Part }
	| { kind: 'part-version'; part: Part; version: PartVersion }
	| { kind: 'part-candidate'; part: Part; candidate: PartCandidate }
	| { kind: 'assembly'; assembly: Assembly }
	| { kind: 'assembly-version'; assembly: Assembly; version: AssemblyVersion }
	| { kind: 'assembly-candidate'; assembly: Assembly; candidate: AssemblyCandidate }
	| { kind: 'hardware'; hardware: Hardware }
	| { kind: 'lasercut'; lasercut: LaserCutPart };

const uidIndex = new Map<string, UidMatch>();
for (const part of PARTS) {
	uidIndex.set(part.uid, { kind: 'part', part });
	for (const version of part.versions ?? [])
		if (version.uid && version.uid !== part.uid) uidIndex.set(version.uid, { kind: 'part-version', part, version });
	for (const candidate of part.candidates ?? []) uidIndex.set(candidate.uid, { kind: 'part-candidate', part, candidate });
}
for (const assembly of ASSEMBLIES) {
	uidIndex.set(assembly.uid, { kind: 'assembly', assembly });
	for (const version of assembly.versions ?? [])
		if (version.uid && version.uid !== assembly.uid) uidIndex.set(version.uid, { kind: 'assembly-version', assembly, version });
	for (const candidate of assembly.candidates ?? []) uidIndex.set(candidate.uid, { kind: 'assembly-candidate', assembly, candidate });
}
for (const hardware of HARDWARE) if (hardware.uid) uidIndex.set(hardware.uid, { kind: 'hardware', hardware });
for (const lasercut of LASER_CUT_PARTS) if (lasercut.uid) uidIndex.set(lasercut.uid, { kind: 'lasercut', lasercut });

export function resolveUid(uid: string): UidMatch | undefined {
	return uidIndex.get(uid.trim().toLowerCase());
}
export function allUids(): string[] {
	return [...uidIndex.keys()];
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
/** Split `total` across `weights` as whole units, keeping the proportions and
 *  summing to exactly `total` (largest remainder). Used when a part's printed
 *  quantity has been edited away from what the machine needs and its colours
 *  have to follow: 3 of 4 charcoal and 1 of 4 white, asked for 2, is 2 and 0
 *  rather than a fractional spool. */
export function apportion(weights: number[], total: number): number[] {
	const sum = weights.reduce((a, b) => a + b, 0);
	if (total <= 0 || weights.length === 0) return weights.map(() => 0);
	if (sum <= 0) return weights.map((_, i) => (i === 0 ? total : 0));
	const exact = weights.map((w) => (w / sum) * total);
	const out = exact.map(Math.floor);
	let left = total - out.reduce((a, b) => a + b, 0);
	// hand the remainder to the largest fractional parts first
	const order = exact
		.map((v, i) => ({ i, frac: v - Math.floor(v) }))
		.sort((a, b) => b.frac - a.frac);
	for (const { i } of order) {
		if (left <= 0) break;
		out[i] += 1;
		left -= 1;
	}
	return out;
}

export function buyList(
	layers: number,
	roleColors: Record<string, string>,
	/** How many of this part are actually being printed (0 = not printing it). */
	qtyOf: (id: string) => number,
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
		const want = qtyOf(part.id);
		if (want <= 0) continue;
		const each = effectiveGrams(part, inclSupport(part.id));
		const vc = variantCount(part.id);
		// The colour split is authored per machine, so scale it to whatever is
		// actually being printed. Unedited, this is the identity.
		const units =
			vc !== null ? colorUnits(part, vc, roleColors) : machineColorUnits(part, layers, roleColors);
		const counts = apportion(
			units.map((u) => u.count),
			want
		);
		units.forEach((u, i) => {
			const key = u.colorId ?? '__any__';
			byColor.set(key, (byColor.get(key) ?? 0) + each * counts[i]);
		});
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
