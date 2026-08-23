/**
 * Searching, as one thing the whole site shares.
 *
 * Two halves, deliberately split:
 *
 *   - the **matcher** (`scoreEntry`, `search`) knows nothing about the catalog.
 *     It takes a query and a `Searchable` — a name, an optional 4-character
 *     uid, a slug id, keywords, prose — and returns a score plus the character
 *     ranges that matched, so a caller can highlight them. Any list on the site
 *     filters through it, which is why the parts list, the hardware list and
 *     the palette all rank the same way.
 *   - the **index** (`CATALOG_INDEX`) is every thing the catalog names, flattened
 *     into one array of `SearchItem`: parts, their superseded versions and their
 *     candidates, assemblies and theirs, hardware, laser-cut sheets, framing
 *     pieces, sections and the site's own pages.
 *
 * ## The ranking, and why it is shaped this way
 *
 * The load-bearing case is someone holding a printed part, reading the four
 * characters engraved on it, and typing them. That has to beat everything else
 * the moment it is complete — but it must not swamp the far more common case of
 * typing the first letters of a name. So a *complete* uid outranks any name
 * match, while a *partial* uid sits below a name that starts with the same
 * letters. Typing `s` puts Stator first; typing `s1` leaves only the ids,
 * because no part is called "s1". Nothing branches on query shape to do that —
 * it falls out of the weights.
 *
 * Everything runs in the browser over a few hundred entries, so every keystroke
 * re-scores the whole index and there is no debounce to feel.
 */
import {
	ASSEMBLIES,
	FOLDERS,
	HARDWARE,
	PARTS,
	SECTIONS,
	fmtDate,
	getAssembly,
	getFolder,
	hardwareImage,
	plainDescription,
	type Assembly,
	type Hardware,
	type Part
} from './filament';
import { FRAMING_PIECES } from './framing';
import { LASER_CUT_PARTS } from './lasercut';

// ---------------------------------------------------------------- the matcher

/** A half-open `[start, end)` slice of a field that the query matched. */
export type Range = [number, number];

/** Anything the matcher can rank. Every field is optional but `name`. */
export type Searchable = {
	name: string;
	/** The 4 characters stamped into a print. Exact match wins outright. */
	uid?: string;
	/** The catalog slug, e.g. `fan-bracket-40mm`. */
	id?: string;
	/** Alternate names, categories, sizes — anything worth matching but not showing. */
	keywords?: string[];
	/** Prose. Matched last and weakly, since a word can appear in any description. */
	text?: string;
};

export type Hit = {
	score: number;
	/** Where in the name it matched, when it did — for highlighting. */
	name: Range | null;
	/** Where in the uid it matched, when it did. */
	uid: Range | null;
};

/** Lowercase, strip accents, and fold the typographic characters the catalog
 *  actually uses (`M5 × 16`, `3/8″`) onto what a keyboard produces. */
function norm(s: string): string {
	return s
		.toLowerCase()
		.normalize('NFKD')
		.replace(/[\u0300-\u036f]/g, '')
		.replace(/[×✕]/g, 'x')
		.replace(/[″”“]/g, '"')
		.replace(/[′’‘]/g, "'")
		.replace(/[–—]/g, '-');
}

/** The same text with every separator gone, so `m3x8` finds `M3 × 8` and
 *  `cchannel` finds `C-channel`. Positions are lost, so this only ever sets a
 *  score, never a highlight range. */
const squash = (s: string) => norm(s).replace(/[^a-z0-9]/g, '');

/** Is `q` a subsequence of `text` — the loosest match we accept, and only for
 *  queries long enough that it means something. `stbrk` finds `Stator bracket`. */
function isSubsequence(q: string, text: string): boolean {
	let i = 0;
	for (const ch of text) {
		if (ch === q[i]) i++;
		if (i === q.length) return true;
	}
	return false;
}

/** Index of the first word in `text` that starts with `q`, or -1. Words break on
 *  anything that isn't alphanumeric, so `bracket` hits `40 mm Fan Bracket` and
 *  `channel` hits `C-channel`. */
function wordStart(q: string, text: string): number {
	let at = 0;
	while (at <= text.length - q.length) {
		const i = text.indexOf(q, at);
		if (i < 0) return -1;
		if (i === 0 || !/[a-z0-9]/.test(text[i - 1])) return i;
		at = i + 1;
	}
	return -1;
}

// The weights. Read them as one table rather than as separate numbers: the
// order between them IS the ranking rule, and the gaps are wide enough that a
// tie-break (see `score` below) can never reorder two different rungs.
const W = {
	uidExact: 1200, // the whole point: four characters off a print
	nameExact: 1000,
	idExact: 900,
	namePrefix: 820,
	uidPrefix: 700, // below namePrefix, so `s` is Stator before it is an id
	nameWord: 640,
	idPrefix: 600,
	idWord: 520,
	keywordPrefix: 480,
	nameSubstring: 420,
	squashed: 380,
	idSubstring: 300,
	keywordSubstring: 260,
	textSubstring: 160,
	subsequence: 120
} as const;

/** Below this length a query only matches from the start of a name, a word, an
 *  id or a uid. One or two characters appear inside almost every description,
 *  and a result list that reacts to `a` by showing everything is worse than one
 *  that shows the handful of things actually beginning with it. */
const PREFIX_ONLY_BELOW = 3;

function scoreToken(raw: string, s: Searchable): Hit | null {
	const q = norm(raw);
	if (!q) return null;
	const loose = q.length >= PREFIX_ONLY_BELOW;

	const name = norm(s.name);
	const uid = s.uid ? norm(s.uid) : '';
	const id = s.id ? norm(s.id) : '';

	// A complete uid is unambiguous — nothing else it could have meant.
	if (uid && uid === q) return { score: W.uidExact, name: null, uid: [0, q.length] };
	if (name === q) return { score: W.nameExact, name: [0, name.length], uid: null };
	if (id && id === q) return { score: W.idExact, name: null, uid: null };

	if (name.startsWith(q)) return { score: W.namePrefix, name: [0, q.length], uid: null };
	if (uid.startsWith(q)) return { score: W.uidPrefix, name: null, uid: [0, q.length] };

	const nw = wordStart(q, name);
	if (nw >= 0) return { score: W.nameWord, name: [nw, nw + q.length], uid: null };

	if (id.startsWith(q)) return { score: W.idPrefix, name: null, uid: null };
	if (wordStart(q, id) >= 0) return { score: W.idWord, name: null, uid: null };

	for (const k of s.keywords ?? []) {
		if (norm(k).startsWith(q)) return { score: W.keywordPrefix, name: null, uid: null };
	}

	if (!loose) return null;

	const ns = name.indexOf(q);
	if (ns >= 0) return { score: W.nameSubstring, name: [ns, ns + q.length], uid: null };

	const sq = squash(raw);
	if (sq && squash(s.name).includes(sq)) return { score: W.squashed, name: null, uid: null };

	if (id.includes(q)) return { score: W.idSubstring, name: null, uid: null };
	for (const k of s.keywords ?? []) {
		if (norm(k).includes(q)) return { score: W.keywordSubstring, name: null, uid: null };
	}
	if (s.text && norm(s.text).includes(q)) return { score: W.textSubstring, name: null, uid: null };
	if (isSubsequence(q, name)) return { score: W.subsequence, name: null, uid: null };

	return null;
}

/**
 * Rank one entry against a query. Null means it doesn't match at all.
 *
 * A multi-word query has to hit on *every* word — `fan bracket` must not return
 * every bracket — but the whole phrase gets its own shot first, so a name that
 * literally contains "fan bracket" outranks one that happens to contain both
 * words far apart.
 */
export function scoreEntry(query: string, s: Searchable): Hit | null {
	const words = query.trim().split(/\s+/).filter(Boolean);
	if (!words.length) return null;
	if (words.length === 1) return scoreToken(words[0], s);

	let sum = 0;
	let best: Hit | null = null;
	for (const w of words) {
		const hit = scoreToken(w, s);
		if (!hit) return null;
		sum += hit.score;
		if (!best || hit.score > best.score) best = hit;
	}
	const phrase = scoreToken(words.join(' '), s);
	const spread = sum / words.length;
	return phrase && phrase.score >= spread ? phrase : { ...(best as Hit), score: spread };
}

/** A ranked entry, carrying the hit so the caller can highlight what matched. */
export type Ranked<T> = { item: T; hit: Hit };

/**
 * Rank a list, best first. `boost` lets the caller nudge whole classes of thing
 * — the catalog uses it to keep a current part above its own superseded
 * versions when their names are identical, which they always are.
 */
export function search<T>(
	query: string,
	items: readonly T[],
	toSearchable: (item: T) => Searchable,
	opts: { limit?: number; boost?: (item: T) => number } = {}
): Ranked<T>[] {
	if (!query.trim()) return [];
	const out: Ranked<T>[] = [];
	for (const item of items) {
		const s = toSearchable(item);
		const hit = scoreEntry(query, s);
		if (!hit) continue;
		// Tie-break on brevity: for `s`, "Stator" is a better guess than "Stator
		// bracket housing spacer". Kept well under the gap between two weights so
		// it can only ever reorder within a rung.
		const tune = (opts.boost?.(item) ?? 0) - Math.min(s.name.length, 60) * 0.4;
		out.push({ item, hit: { ...hit, score: hit.score + tune } });
	}
	out.sort((a, b) => b.hit.score - a.hit.score);
	return opts.limit ? out.slice(0, opts.limit) : out;
}

// ------------------------------------------------------------------ the index

/** What a result *is*. Each gets its own chip in the palette, because "the
 *  current stator" and "a rejected test print of the stator" answer very
 *  different questions and read almost identically otherwise. */
export type ResultKind =
	| 'part'
	| 'part-version'
	| 'part-candidate'
	| 'assembly'
	| 'assembly-version'
	| 'assembly-candidate'
	| 'hardware'
	| 'lasercut'
	| 'framing'
	| 'section'
	| 'page';

/** The palette's filter chips. `uid` is the explicit "I am reading characters
 *  off a print" mode: it matches nothing but stamped ids. */
export type SearchScope = 'all' | 'parts' | 'assemblies' | 'hardware' | 'uid';

export type SearchItem = Searchable & {
	/** Unique across the whole index; a uid isn't enough (a part and its current
	 *  version share one) and neither is an id. */
	key: string;
	kind: ResultKind;
	scope: Exclude<SearchScope, 'all' | 'uid'>;
	/** What the chip says. */
	label: string;
	/** A qualifier on the chip: `v1.2`, `superseded`, `rejected`. */
	note?: string;
	/** Where the thing lives, one line. */
	subtitle?: string;
	href: string;
	image?: string | null;
	/** Ranking nudge — see `search`. */
	boost: number;
};

export const SCOPES: { id: SearchScope; label: string; hint: string }[] = [
	{ id: 'all', label: 'Everything', hint: 'Parts, assemblies, hardware, pages' },
	{ id: 'parts', label: 'Parts', hint: 'Printed, laser-cut and framing pieces' },
	{ id: 'assemblies', label: 'Assemblies', hint: 'What bolts to what' },
	{ id: 'hardware', label: 'Hardware', hint: 'Screws, bearings, motors, boards' },
	{ id: 'uid', label: 'Stamped id', hint: 'Only the 4 characters engraved on a print' }
];

const sectionNames = new Map(SECTIONS.map((s) => [s.id, s.name]));

/** Where a printed part lives, for the second line of a result. Prefers the
 *  assemblies that list it — that is what someone recognises — and falls back to
 *  the sections it is counted in for the parts the tree hasn't reached. */
function partHome(p: Part): string {
	const asms = ASSEMBLIES.filter((a) => (a.lines ?? []).some((l) => l.part === p.id));
	if (asms.length) return asms.map((a) => a.name).join(' · ');
	const sections = Object.keys(p.quantities)
		.map((id) => sectionNames.get(id))
		.filter(Boolean);
	if (sections.length) return sections.join(' · ');
	return getFolder(p.folder ?? null)?.name ?? 'Not placed yet';
}

/** Every word worth matching on a part but not worth showing. */
function partKeywords(p: Part): string[] {
	return [
		...(p.aliases ?? []),
		...Object.keys(p.quantities).map((id) => sectionNames.get(id) ?? id),
		getFolder(p.folder ?? null)?.name ?? '',
		p.variant_name ?? '',
		getAssembly(p.assembly)?.name ?? '',
		...(p.attributes ?? []).map((a) => `${a.label} ${a.value}`)
	].filter(Boolean);
}

function hardwareKeywords(h: Hardware): string[] {
	const c = h.cots;
	return [
		h.category ?? '',
		c?.type ?? '',
		c?.size ?? '',
		c?.variant ?? '',
		c?.length_mm ? `${c.length_mm}mm` : '',
		// The two ways people write a screw, so `m3x8` and `M3 8mm` both land.
		c?.size && c.length_mm ? `${c.size}x${c.length_mm}` : '',
		...(h.attributes ?? []).map((a) => `${a.label} ${a.value}`)
	].filter(Boolean);
}

/** An assembly's members by name — searching "stator" should surface the
 *  C-channel drive it belongs to, not only the stator itself. */
function assemblyKeywords(a: Assembly): string[] {
	return (a.lines ?? [])
		.map((l) => (l.part ? l.part : l.assembly ? (getAssembly(l.assembly)?.name ?? '') : ''))
		.filter(Boolean);
}

const PAGES: { name: string; href: string; text: string; keywords: string[] }[] = [
	{ name: '3D printed parts', href: '/', text: 'Configure a build, pick colours and download the STLs.', keywords: ['stl', 'download', 'filament', 'print', 'calculator', 'manifest'] },
	{ name: 'Aluminium framing', href: '/framing', text: 'Every 2020 extrusion cut length and how to get them out of 1 m bars.', keywords: ['extrusion', '2020', 'cut', 'bar', 'aluminum', 't-slot'] },
	{ name: 'Laser cut parts', href: '/lasercut', text: 'The flat plywood DXFs, and how to cut them by hand.', keywords: ['dxf', 'plywood', 'sheet', 'jigsaw'] },
	{ name: 'Hardware', href: '/hardware', text: 'Screws, nuts, inserts, bearings and where to buy them.', keywords: ['bom', 'buy', 'cart', 'sourcing', 'vendor', 'cots'] },
	{ name: 'Machine assembly', href: '/assembly', text: 'The machine as a tree: what bolts to what, top to bottom.', keywords: ['tree', 'bom', 'structure'] },
	{ name: 'Changes and improvements', href: '/changes', text: 'What is planned or broken on a part before you print it.', keywords: ['planned', 'broken', 'todo', 'revision'] },
	{ name: 'Top plate hand-cut guide', href: '/lasercut/top-plate-guide', text: 'Cutting the top plate with a jigsaw and a drill instead of a laser.', keywords: ['handcut', 'jigsaw', 'guide', 'printable'] }
];

// Current things sit a rung above their own history, which matters because a
// version carries the same name as its part and would otherwise tie with it.
// Printed parts edge out everything else on a tie because this is a tool for
// deciding what to print — typing `s` should land on the Stator before it lands
// on framing piece B, which is also called a spoke and is also a shorter word.
// Every value here is far smaller than the gap between two weights, so these can
// only ever reorder things that already matched the same way.
const BOOST = { printed: 70, current: 60, framing: 35, page: 30, historic: 0, retired: -40 } as const;

function buildIndex(): SearchItem[] {
	const items: SearchItem[] = [];

	for (const p of PARTS) {
		const home = partHome(p);
		const keywords = partKeywords(p);
		const text = plainDescription(p.description);
		items.push({
			key: `part:${p.id}`,
			kind: 'part',
			scope: 'parts',
			label: '3D printed',
			note: `v${p.version}`,
			name: p.name,
			uid: p.uid,
			id: p.id,
			keywords,
			text,
			subtitle: home,
			href: `/part/${p.id}`,
			image: p.render,
			boost: BOOST.printed
		});
		// The part's own uid is the newest version's, and it is already indexed
		// above as the part — listing it twice would answer one query with two
		// rows saying the same thing.
		for (const v of p.versions ?? []) {
			if (!v.uid || v.uid === p.uid) continue;
			items.push({
				key: `part-version:${p.id}:${v.uid}`,
				kind: 'part-version',
				scope: 'parts',
				label: 'Old version',
				note: `v${v.version}`,
				name: p.name,
				uid: v.uid,
				id: p.id,
				keywords,
				text: v.message,
				subtitle: `Superseded ${fmtDate(v.date)} · now v${p.version}`,
				href: `/u/${v.uid}`,
				image: v.render ?? p.render,
				boost: BOOST.historic
			});
		}
		for (const c of p.candidates ?? []) {
			const state = c.rejected_at
				? `Rejected ${fmtDate(c.rejected_at)}`
				: c.superseded_by
					? `Superseded by ${c.superseded_by.toUpperCase()}`
					: 'Under test';
			items.push({
				key: `part-candidate:${p.id}:${c.uid}`,
				kind: 'part-candidate',
				scope: 'parts',
				label: 'Candidate',
				note: c.rejected_at ? 'rejected' : c.superseded_by ? 'superseded' : 'under test',
				name: c.name ? `${p.name} (${c.name})` : p.name,
				uid: c.uid,
				id: p.id,
				keywords,
				text: c.message,
				subtitle: `A test revision for ${p.name} · ${state}`,
				href: `/u/${c.uid}`,
				image: c.render ?? p.render,
				boost: c.rejected_at || c.superseded_by ? BOOST.retired : BOOST.historic
			});
		}
	}

	for (const a of ASSEMBLIES) {
		const keywords = assemblyKeywords(a);
		items.push({
			key: `assembly:${a.id}`,
			kind: 'assembly',
			scope: 'assemblies',
			label: 'Assembly',
			note: a.version ? `v${a.version}` : a.status === 'stub' ? 'stub' : undefined,
			name: a.name,
			uid: a.uid,
			id: a.id,
			keywords,
			text: plainDescription(a.description),
			subtitle: `${(a.lines ?? []).length} member${(a.lines ?? []).length === 1 ? '' : 's'}`,
			href: `/assembly?focus=${encodeURIComponent(a.id)}`,
			boost: BOOST.current
		});
		for (const v of a.versions ?? []) {
			if (!v.uid || v.uid === a.uid) continue;
			items.push({
				key: `assembly-version:${a.id}:${v.uid}`,
				kind: 'assembly-version',
				scope: 'assemblies',
				label: 'Old structure',
				note: `v${v.version}`,
				name: a.name,
				uid: v.uid,
				id: a.id,
				keywords,
				text: v.message,
				subtitle: `Superseded ${fmtDate(v.date)}`,
				href: `/u/${v.uid}`,
				boost: BOOST.historic
			});
		}
		for (const c of a.candidates ?? []) {
			items.push({
				key: `assembly-candidate:${a.id}:${c.uid}`,
				kind: 'assembly-candidate',
				scope: 'assemblies',
				label: 'Candidate',
				note: c.rejected_at ? 'rejected' : c.superseded_by ? 'superseded' : 'under test',
				name: c.name ? `${a.name} (${c.name})` : a.name,
				uid: c.uid,
				id: a.id,
				keywords,
				text: c.message,
				subtitle: `An alternative bill of materials for ${a.name}`,
				href: `/u/${c.uid}`,
				boost: c.rejected_at || c.superseded_by ? BOOST.retired : BOOST.historic
			});
		}
	}

	for (const h of HARDWARE) {
		items.push({
			key: `hardware:${h.id}`,
			kind: 'hardware',
			scope: 'hardware',
			label: 'Hardware',
			name: h.name,
			uid: h.uid,
			id: h.id,
			keywords: hardwareKeywords(h),
			text: plainDescription(h.description),
			subtitle: h.category ?? 'Off the shelf',
			href: `/part/${h.id}`,
			image: hardwareImage(h)?.src ?? null,
			boost: BOOST.current
		});
	}

	for (const l of LASER_CUT_PARTS) {
		items.push({
			key: `lasercut:${l.id}`,
			kind: 'lasercut',
			scope: 'parts',
			label: 'Laser cut',
			name: l.name,
			uid: l.uid,
			id: l.id,
			keywords: ['dxf', 'plywood', 'sheet', l.thicknessIn, `${l.thicknessMm}mm`],
			text: plainDescription(l.description),
			subtitle: `${l.thicknessIn} plywood · ${Math.round(l.widthMm)} × ${Math.round(l.heightMm)} mm`,
			href: '/lasercut',
			image: l.preview,
			boost: BOOST.current
		});
	}

	for (const f of FRAMING_PIECES) {
		items.push({
			key: `framing:${f.letter}`,
			kind: 'framing',
			scope: 'parts',
			label: 'Framing',
			note: f.letter,
			name: f.name,
			id: f.letter.toLowerCase(),
			keywords: ['2020', 'extrusion', 'aluminium', 'aluminum', `${f.len}mm`, f.category],
			text: f.from,
			subtitle: `Piece ${f.letter} · ${f.len} mm of 2020 extrusion`,
			href: '/framing',
			boost: BOOST.framing
		});
	}

	for (const s of SECTIONS) {
		items.push({
			key: `section:${s.id}`,
			kind: 'section',
			scope: 'parts',
			label: 'Section',
			name: s.name,
			id: s.id,
			keywords: ['section', 'group'],
			subtitle: s.scales_with_layers ? 'One per layer' : 'One per machine',
			href: `/#section-${s.id}`,
			boost: BOOST.page
		});
	}
	for (const f of FOLDERS) {
		items.push({
			key: `folder:${f.id}`,
			kind: 'section',
			scope: 'parts',
			label: 'Group',
			name: f.name,
			id: f.id,
			text: f.description,
			subtitle: 'A group in the parts list',
			href: '/',
			boost: BOOST.page
		});
	}

	for (const p of PAGES) {
		items.push({
			key: `page:${p.href}`,
			kind: 'page',
			scope: 'parts',
			label: 'Page',
			name: p.name,
			keywords: p.keywords,
			text: p.text,
			subtitle: p.text,
			href: p.href,
			boost: BOOST.page
		});
	}

	return items;
}

/** Built once, at module load. A few hundred entries off already-parsed JSON —
 *  cheaper than the work of deciding when to build it lazily. */
export const CATALOG_INDEX: SearchItem[] = buildIndex();

/** Pages and sections aren't things you hold, so they have no stamped id and
 *  are simply absent from the id scope. */
const inScope = (item: SearchItem, scope: SearchScope) =>
	scope === 'all' ? true : scope === 'uid' ? !!item.uid : item.scope === scope;

/** `#s1qc` and `id:s1qc` mean "this is a stamped id", so someone who knows what
 *  they're typing can say so without reaching for the scope chips. */
const ID_PREFIX = /^(?:#|id:)\s*/i;
export function readScopePrefix(query: string): { query: string; scope: SearchScope | null } {
	const m = query.match(ID_PREFIX);
	return m ? { query: query.slice(m[0].length), scope: 'uid' } : { query, scope: null };
}

/** The palette's one call: rank the whole catalog inside a scope. In the id
 *  scope only the uid is considered, so a part whose *name* contains the
 *  characters can't crowd out the print you are holding. */
export function searchCatalog(query: string, scope: SearchScope = 'all', limit = 40): Ranked<SearchItem>[] {
	const pool = CATALOG_INDEX.filter((i) => inScope(i, scope));
	const view: (item: SearchItem) => Searchable =
		scope === 'uid' ? (i) => ({ name: i.uid ?? '', uid: i.uid }) : (i) => i;
	const ranked = search(query, pool, view, { limit, boost: (i) => i.boost });
	// In the id scope the matcher was handed the uid as the name, so the name
	// range it reports points into the uid. Move it where the row expects it.
	return scope === 'uid'
		? ranked.map((r) => ({ ...r, hit: { ...r.hit, uid: r.hit.uid ?? r.hit.name, name: null } }))
		: ranked;
}

/** Look one item up by the key the palette persists in "recent". */
const byKey = new Map(CATALOG_INDEX.map((i) => [i.key, i]));
export const itemByKey = (key: string): SearchItem | undefined => byKey.get(key);
