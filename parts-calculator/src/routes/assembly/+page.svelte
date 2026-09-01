<script lang="ts">
	import {
		Check,
		ChevronDown,
		ChevronRight,
		Download,
		EllipsisVertical,
		ExternalLink,
		FlaskConical,
		History,
		Info,
		SlidersHorizontal,
		X,
		Zap
	} from 'lucide-svelte';
	import ConnectionBraces, { braceGroups } from '$lib/components/ConnectionBraces.svelte';
	import DropdownMenu from '$lib/components/DropdownMenu.svelte';
	import AlternativeBadge from '$lib/components/AlternativeBadge.svelte';
	import ConflictBadge from '$lib/components/ConflictBadge.svelte';
	import AssemblyDescription from '$lib/components/AssemblyDescription.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import LayerControl from '$lib/components/LayerControl.svelte';
	import PartDetailModal from '$lib/components/PartDetailModal.svelte';
	import AssemblyDetailModal from '$lib/components/AssemblyDetailModal.svelte';
	import HardwareDetailModal from '$lib/components/HardwareDetailModal.svelte';
	import HardwareIcon from '$lib/components/HardwareIcon.svelte';
	import ImageStrip from '$lib/components/ImageStrip.svelte';
	import SearchField from '$lib/components/search/SearchField.svelte';
	import Seo from '$lib/components/Seo.svelte';
	import { scoreEntry } from '$lib/search';
	import { colorStore } from '$lib/colors.svelte';
	import {
		ASSEMBLIES,
		commitUrl,
		docsUrl,
		fmtDate,
		getAssembly,
		getHardware,
		getLasercut,
		getPart,
		hardwareImage,
		JOIN_LABELS,
		lineQty,
		PARTS,
		plainDescription,
		primaryColorId,
		screwTravel,
		SETTINGS,
		TAGS,
		type CatalogTag,
		type Assembly,
		type AssemblyLine,
		type AssemblySnapshotLine,
		type Connection,
		type Hardware,
		type Joining,
		type Part,
		type PartVersion
	} from '$lib/filament';
	import { layerStore } from '$lib/layers.svelte';
	import changelog from '$lib/data/changelog.generated.json';
	import { page } from '$app/state';
	import { browser } from '$app/environment';
	import { afterNavigate, replaceState } from '$app/navigation';
	import { onMount } from 'svelte';
	import { assemblyCsv } from '$lib/parts-csv';
	import { download, exportSpec, filename } from '$lib/csv';

	// The connection methods extend JoinMethod with the anchor kinds
	// (check_connections.py is the authority on the enum).
	const CONN_LABELS: Record<string, string> = {
		...JOIN_LABELS,
		thread: 'threaded',
		insert: 'heat-set insert',
		nut: 'nut',
		tnut: 'T-nut',
		gravity: 'gravity'
	};

	// Experimental view of the unified parts system (notes/UNIFIED-PARTS-SYSTEM.md):
	// the machine as a recursive assembly tree whose lines reference printed parts,
	// sub-assemblies, and (eventually) all the COTS hardware. Most nodes are stubs;
	// the chute core is the first branch carrying real hardware via `requires`.
	const layers = $derived(layerStore.sizes.length);

	// ---- collapsing the tree -------------------------------------------------
	// Every node can fold. The record below is also the authored default-open
	// set: only the machine itself starts open, so the page opens as a one-line
	// table of contents instead of the whole bill of materials at once.
	let expanded = $state<Record<string, boolean>>({ machine: true });
	const isOpen = (id: string) => (filtering ? true : (expanded[id] ?? false));
	function toggle(id: string) {
		expanded[id] = !(expanded[id] ?? false);
	}

	// The ⋮ menu on a node: expand or collapse its whole subtree, itself
	// included. One open menu at a time, keyed by assembly id.
	let menuFor = $state<string | null>(null);
	function setSubtree(id: string, open: boolean, seen = new Set<string>()) {
		if (seen.has(id)) return;
		seen.add(id);
		expanded[id] = open;
		for (const line of getAssembly(id)?.lines ?? []) {
			if (line.assembly) setSubtree(line.assembly, open, seen);
		}
		menuFor = null;
	}
	function onWindowClick(e: MouseEvent) {
		if (menuFor && !(e.target as Element)?.closest?.('[data-asm-menu]')) menuFor = null;
	}
	function onWindowKey(e: KeyboardEvent) {
		if (e.key === 'Escape') menuFor = null;
	}

	// First parent wins for a subtree shared by two branches — good enough for
	// walking upward from a focus target. `treeOrder` is the same walk recorded
	// as a list, so the ids written to the URL come out parents-first instead of
	// in whatever order they happened to be unfolded.
	const parentOf = new Map<string, string>();
	const treeOrder: string[] = ['machine'];
	{
		const walk = (id: string) => {
			for (const line of getAssembly(id)?.lines ?? []) {
				if (line.assembly && !parentOf.has(line.assembly)) {
					parentOf.set(line.assembly, id);
					treeOrder.push(line.assembly);
					walk(line.assembly);
				}
			}
		};
		walk('machine');
	}

	// ---- the open tree in the URL --------------------------------------------
	// Which nodes are unfolded IS the view on this page, so it belongs in the
	// address bar: the link you paste reopens the branch you were talking about.
	// `open` lists the unfolded assemblies; `open=` with nothing after it means
	// everything is folded, which is a different thing from no param at all (that
	// one means "the authored default"), and `open=all` is the whole tree, spelled
	// out because the id list for that runs past 500 characters. Query params only
	// exist in the browser — the site is prerendered — so the URL is read on mount,
	// once, and written back from an effect afterwards.
	let focus = $state<string | null>(null);
	let urlReady = $state(false);
	onMount(() => {
		const sp = page.url.searchParams;
		const openParam = sp.get('open');
		if (openParam !== null) {
			expanded = {};
			const ids = openParam === 'all' ? treeOrder : openParam.split(',');
			for (const id of ids) if (getAssembly(id)) expanded[id] = true;
		}

		// ?focus=<assembly id> — the hardware page links here to answer "where does
		// this screw actually go?".
		const target = sp.get('focus');
		focus = target;
		if (!target) return;
		// A collapsed ancestor would hide the thing being pointed at.
		for (let cur: string | undefined = target; cur; cur = parentOf.get(cur)) expanded[cur] = true;
		// Part renders load after first paint and shift everything down, so one
		// scroll lands short. Re-aim a few times while the layout settles.
		const aim = () => document.getElementById(`asm-${target}`)?.scrollIntoView({ block: 'center' });
		const timers = [0, 120, 400, 900].map((t) => setTimeout(aim, t));
		return () => timers.forEach(clearTimeout);
	});

	// Not onMount: on a cold load the router is still initialising then, and
	// replaceState throws if it is called before that finishes. afterNavigate
	// runs once the first navigation has landed, which is exactly late enough.
	afterNavigate(() => (urlReady = true));

	$effect(() => {
		if (!browser || !urlReady) return;
		const open = treeOrder.filter((id) => expanded[id]);
		// location, not page.url: replaceState does not update the page store,
		// so reading it here would resurrect params another writer removed.
		const params = new URLSearchParams(location.search);
		// The default view writes no param, so the bare page keeps a bare URL.
		if (open.length === 1 && open[0] === 'machine') params.delete('open');
		else if (open.length === treeOrder.length) params.set('open', 'all');
		else params.set('open', open.join(','));
		// A comma is legal in a query string, and a list of ids is worth reading
		// in the address bar; URLSearchParams escapes it anyway, so undo that.
		const qs = params.toString().replaceAll('%2C', ',');
		const target = qs ? `${location.pathname}?${qs}` : location.pathname;
		if (target !== location.pathname + location.search) replaceState(target, {});
	});

	// ---- filtering the tree --------------------------------------------------
	// A tree can't be filtered like a list: hiding everything that doesn't match
	// would also hide the branch that tells you WHERE the match is, which is the
	// only reason to search a tree in the first place. So a node survives when it
	// matches or when anything beneath it does, and the path down to a match stays
	// on screen. An assembly that matches by its own name keeps its whole subtree
	// — you asked for the chute core, you want what is in it.
	// Text search and the menu's predicate filters (stable-tagged) AND together;
	// both use the same keep machinery. Order re-sorts each assembly's lines in
	// place. Both menu choices live in the URL (?stable=1&order=name).
	let filter = $state('');
	let fGolden = $state(false);
	let fStable = $state(false);
	let order = $state<'authored' | 'name'>('authored');
	const textActive = $derived(filter.trim().length > 0);
	const filtering = $derived(textActive || fGolden || fStable);

	/** The tags standing on a node's CURRENT version: a tag blesses a moment,
	 *  so a revision after its date leaves it behind on the old version. */
	function tagsFor(id: string): CatalogTag[] {
		return TAGS.filter((t) => {
			if (t.node !== id) return false;
			const m = getPart(id) ?? getAssembly(id);
			const last = m?.versions?.[m.versions.length - 1];
			return !last?.date || last.date <= t.date;
		});
	}
	/** Stability filter: checked levels union — golden alone, stable alone, or
	 *  both at once. Nothing checked means no stability filtering at all. */
	const stableOk = (id: string) => {
		if (!fGolden && !fStable) return true;
		const ts = tagsFor(id);
		return (
			(fGolden && ts.some((t) => t.stability === 'golden')) ||
			(fStable && ts.some((t) => t.stability === 'stable'))
		);
	};

	/** Does this member — printed part, bought part or laser-cut sheet — match? */
	function memberMatches(id: string): boolean {
		if (!stableOk(id)) return false;
		if (!textActive) return true;
		const p = getPart(id);
		if (p) return !!scoreEntry(filter, { name: p.name, uid: p.uid, id: p.id, keywords: p.aliases, text: p.description });
		const h = getHardware(id);
		if (h)
			return !!scoreEntry(filter, {
				name: h.name,
				uid: h.uid,
				id: h.id,
				keywords: [h.category ?? '', h.cots?.size ?? '', h.cots?.type ?? ''].filter(Boolean),
				text: plainDescription(h.description)
			});
		const l = getLasercut(id);
		if (l) return !!scoreEntry(filter, { name: l.name, uid: l.uid, id: l.id, text: l.description });
		return false;
	}

	const keep = $derived.by(() => {
		const assemblies = new Set<string>();
		const members = new Set<string>();
		// What actually matched, as opposed to what is on screen: most of
		// `assemblies` is the path down to a hit, and calling those matches would
		// overstate what was found.
		const matched = new Set<string>();
		if (!filtering) return { assemblies, members, matched };

		// An assembly that matched by name pulls everything under it along.
		const whole = new Set<string>();
		function includeAll(id: string) {
			if (whole.has(id)) return;
			whole.add(id);
			assemblies.add(id);
			for (const line of getAssembly(id)?.lines ?? []) {
				if (line.assembly) includeAll(line.assembly);
				else if (line.part) members.add(line.part);
			}
		}

		// Memoised, and seeded false before recursing, so a subtree shared by two
		// branches is walked once and an authoring typo can't spin forever.
		const seen = new Map<string, boolean>();
		function visit(id: string): boolean {
			const memo = seen.get(id);
			if (memo !== undefined) return memo;
			seen.set(id, false);
			const asm = getAssembly(id);
			if (!asm) return false;
			let hit =
				stableOk(id) &&
				(!textActive ||
					!!scoreEntry(filter, {
						name: asm.name,
						uid: asm.uid,
						id: asm.id,
						text: plainDescription(asm.description)
					}));
			if (hit) {
				matched.add(id);
				includeAll(id);
			}
			else {
				for (const line of asm.lines ?? []) {
					if (line.assembly) {
						if (visit(line.assembly)) hit = true;
					} else if (line.part && memberMatches(line.part)) {
						members.add(line.part);
						matched.add(line.part);
						hit = true;
					}
				}
				if (hit) assemblies.add(id);
			}
			seen.set(id, hit);
			return hit;
		}
		visit('machine');
		return { assemblies, members, matched };
	});

	/** Is this line still on screen? Assemblies self-guard in `node`; members are
	 *  checked here because they have nowhere else to do it. */
	const lineShown = (line: AssemblyLine) =>
		!filtering ||
		(line.assembly ? keep.assemblies.has(line.assembly) : !!line.part && keep.members.has(line.part));

	const matchCount = $derived(keep.matched.size);

	// The filter menu's choices are shareable state too: read in the same mount
	// pass as ?open/?focus, written back through the same urlReady gate. Both
	// writers start from the current search, so neither strips the other's keys.
	onMount(() => {
		const sp = page.url.searchParams;
		fGolden = sp.get('golden') === '1';
		fStable = sp.get('stable') === '1';
		if (sp.get('order') === 'name') order = 'name';
	});
	$effect(() => {
		const want: [string, string | null][] = [
			['golden', fGolden ? '1' : null],
			['stable', fStable ? '1' : null],
			['order', order !== 'authored' ? order : null]
		];
		if (!browser || !urlReady) return;
		const params = new URLSearchParams(location.search);
		if (want.every(([k, v]) => params.get(k) === v)) return;
		for (const [k, v] of want) {
			if (v) params.set(k, v);
			else params.delete(k);
		}
		const qs = params.toString().replaceAll('%2C', ',');
		replaceState(qs ? `${location.pathname}?${qs}` : location.pathname, {});
	});

	// What the badge means. The tree records that a node is incomplete but not
	// which pieces are missing, so the tooltip says exactly that much and no
	// more. Only stubs get a badge: `partial` is true of nearly every assembly
	// right now, so a badge for it was wallpaper — the status still shows in
	// the detail view.
	const STATUS_NOTE = {
		stub: 'Placeholder — nothing has been recorded inside this assembly yet. What it actually contains is not captured anywhere in the data.'
	};

	// ---- assembly versions: view any revision, diff any two ------------------
	// versions[] ends with the current revision; superseded entries carry the
	// lines as they were, each pinned to the member's uid of the day. Viewing an
	// old version swaps the node's line rows for that snapshot; picking a diff
	// base marks what changed between the two.
	let shownVersion = $state<Record<string, string>>({});
	let diffBase = $state<Record<string, string>>({});

	const currentVersion = (asm: Assembly) => String(asm.version ?? '1');

	function memberOf(id: string) {
		return getPart(id) ?? getHardware(id) ?? getLasercut(id) ?? getAssembly(id);
	}
	function memberName(id: string): string {
		return memberOf(id)?.name ?? ghostName(id) ?? id;
	}
	/** Which revision of the member a pinned uid names: its version number, or
	 *  null when the uid predates the member's recorded history. */
	function memberRev(id: string, uid?: string): string | null {
		if (!uid) return null;
		const m = getPart(id) ?? getAssembly(id);
		if (!m) return null;
		if (m.uid === uid) return String(m.version ?? '1');
		return m.versions?.find((v) => v.uid === uid)?.version ?? null;
	}

	/** The line snapshot at one version: the live lines for the current one
	 *  (pinned to each member's current uid, which is what a snapshot taken now
	 *  would say), a versions[] entry's snapshot otherwise. */
	function linesAt(asm: Assembly, v: string): AssemblySnapshotLine[] | null {
		if (v === currentVersion(asm))
			return (asm.lines ?? []).map((l) => ({ ...l, uid: memberOf(l.part ?? l.assembly ?? '')?.uid }));
		return asm.versions?.find((e) => e.version === v)?.lines ?? null;
	}

	type DiffRow = {
		id: string;
		kind: 'same' | 'added' | 'removed' | 'qty' | 'rev';
		old?: AssemblySnapshotLine;
		now?: AssemblySnapshotLine;
	};
	const sumQty = (a: AssemblyLine['qty'], b: AssemblyLine['qty']) =>
		typeof a === 'number' && typeof b === 'number' ? a + b : (`${a} + ${b}` as const);
	/** Line-level diff between two snapshots, keyed by member id. A member
	 *  listed twice is aggregated first, so it can't diff against itself. */
	function diffLines(oldL: AssemblySnapshotLine[], newL: AssemblySnapshotLine[]): DiffRow[] {
		const gather = (ls: AssemblySnapshotLine[]) => {
			const m = new Map<string, AssemblySnapshotLine>();
			for (const l of ls) {
				const k = l.part ?? l.assembly ?? '';
				const g = m.get(k);
				m.set(k, g ? { ...g, qty: sumQty(g.qty, l.qty) as AssemblyLine['qty'] } : { ...l });
			}
			return m;
		};
		const om = gather(oldL);
		const nm = gather(newL);
		const rows: DiffRow[] = [];
		for (const [k, o] of om) {
			const n = nm.get(k);
			if (!n) rows.push({ id: k, kind: 'removed', old: o });
			else if (String(o.qty) !== String(n.qty)) rows.push({ id: k, kind: 'qty', old: o, now: n });
			else if (o.uid && n.uid && o.uid !== n.uid) rows.push({ id: k, kind: 'rev', old: o, now: n });
			else rows.push({ id: k, kind: 'same', old: o, now: n });
		}
		for (const [k, n] of nm) if (!om.has(k)) rows.push({ id: k, kind: 'added', now: n });
		return rows;
	}

	// ---- history -------------------------------------------------------------
	// The rolled-up change log of a subtree, git-log style: a node's history is
	// every change to anything at or below it, attributed to the node where it
	// happened. Two sources, merged: versions[] entries (authoritative — written
	// at stamp time, required since the stamp rule) and changelog.generated.json,
	// structural changes reconstructed from the git history of parts.json for
	// the era before the rule. Every row is a MOMENT: click it and the tree
	// below re-renders at that moment — as the change (diffed against the state
	// just before), against the current tree, or as a plain snapshot. Stable
	// tags are rows on the same timeline.
	type HistoryEvent = {
		date: string;
		commit?: string | null;
		pr?: number | null;
		seq?: number;
		node: string;
		kind: string;
		version?: string;
		breaking?: boolean;
		detail?: string;
		message?: string;
		tag?: CatalogTag;
	};
	const KIND_LABEL: Record<string, string> = {
		'part-added': 'added',
		'assembly-added': 'added',
		'part-removed': 'removed',
		'assembly-removed': 'removed',
		'qty-changed': 'qty'
	};
	const prBase = (SETTINGS.commit_base_url ?? '').replace(/commit\/$/, 'pull/');
	type ChangelogAsm = Record<string, { timeline: { seq: number; date: string; lines: AssemblyLine[] | null }[] }>;
	const eraAsm = changelog.assemblies as ChangelogAsm;
	const eraCommits = changelog.commits as Record<string, { seq: number; date: string }>;
	const eraThrough = changelog.through as string;
	const ghostName = (id: string) => (changelog.ghosts as Record<string, string>)[id];
	// Recorded revisions sit after every same-date reconstructed commit; the cap
	// keeps them below NOW. DAY_END is later still: the moment after everything
	// recorded on a date, used when an event can't be placed more precisely.
	const VSEQ = 10_000_000;
	const DAY_END = VSEQ * 2;
	const ALL_EVENTS: HistoryEvent[] = [
		...(changelog.events as HistoryEvent[]),
		...[...PARTS, ...ASSEMBLIES].flatMap((item) => {
			// A single entry means nothing ever changed (the generator writes a
			// synthetic "Initial version." for every part) — no history to show.
			const all = item.versions ?? [];
			if (all.length < 2) return [];
			return all.map(
				(v, i): HistoryEvent => ({
					date: v.date ?? '',
					commit: v.commit,
					seq: VSEQ + i,
					node: item.id,
					kind: 'revision',
					version: i > 0 ? `v${all[i - 1].version}→v${v.version}` : `v${v.version}`,
					breaking: v.breaking,
					message: v.message
				})
			);
		}),
		...TAGS.map(
			(t): HistoryEvent => ({
				date: t.date,
				commit: t.commit,
				node: t.node,
				kind: 'tag',
				message: t.message,
				tag: t
			})
		)
	].sort((a, b) => (b.date || '').localeCompare(a.date || '') || (b.pr ?? 0) - (a.pr ?? 0));

	let historyFor = $state<Record<string, boolean>>({});
	const subtreeCache = new Map<string, Set<string>>();
	function subtreeIds(id: string): Set<string> {
		const hit = subtreeCache.get(id);
		if (hit) return hit;
		const set = new Set<string>();
		const walk = (nid: string) => {
			if (!nid || set.has(nid)) return;
			set.add(nid);
			for (const line of getAssembly(nid)?.lines ?? []) walk(line.part ?? line.assembly ?? '');
		};
		walk(id);
		subtreeCache.set(id, set);
		return set;
	}
	function historyOf(id: string): HistoryEvent[] {
		const ids = subtreeIds(id);
		return ALL_EVENTS.filter((e) => ids.has(e.node));
	}
	/** A history row's node opens whatever detail view its kind has. */
	function openNode(id: string) {
		const p = getPart(id);
		if (p) return openPart(p);
		const h = getHardware(id);
		if (h) return openHardware(h);
		if (getAssembly(id)) openAssembly(id);
	}

	// ---- time travel ---------------------------------------------------------
	// A moment on the timeline is a key (date, seq) — seq orders the same-day
	// reconstructed commits, VSEQ+ the recorded revisions after them. Any two
	// keys diff: the tree renders from the union of both states, per-assembly
	// diffLines marking what moved between them. `a === b` is a plain snapshot.
	type TKey = { d: string; s: number };
	const NOW: TKey = { d: '9999-12-31', s: Number.MAX_SAFE_INTEGER };
	const keyLE = (x: TKey, y: TKey) => x.d < y.d || (x.d === y.d && x.s <= y.s);
	type TimeMode = 'change' | 'vs-now' | 'tree';
	let timeView = $state<{ point: TKey; before: TKey; label: string; mode: TimeMode } | null>(null);
	const viewKeys = $derived(
		!timeView
			? null
			: timeView.mode === 'change'
				? { a: timeView.before, b: timeView.point }
				: timeView.mode === 'vs-now'
					? { a: timeView.point, b: NOW }
					: { a: timeView.point, b: timeView.point }
	);

	/** Every recorded state of an assembly's lines, oldest first: the era
	 *  timeline, then versions[] snapshots dated past the era's horizon (the
	 *  stamp rule guarantees those exist for every later structural change). */
	const stateCache = new Map<string, { d: string; s: number; lines: AssemblyLine[] | null }[]>();
	function statesOf(id: string) {
		const hit = stateCache.get(id);
		if (hit) return hit;
		const st = (eraAsm[id]?.timeline ?? []).map((t) => ({ d: t.date, s: t.seq, lines: t.lines }));
		const asm = getAssembly(id);
		const vs = asm?.versions ?? [];
		vs.forEach((v, i) => {
			// >= : a stamp dated the era's own horizon (same-day) must still
			// resolve. When the era already recorded that change, the extra
			// state carries identical lines, so resolution is unaffected.
			if (v.date && v.date >= eraThrough)
				st.push({ d: v.date, s: VSEQ + i, lines: i === vs.length - 1 ? (asm!.lines ?? []) : (v.lines ?? null) });
		});
		stateCache.set(id, st);
		return st;
	}
	/** The assembly's lines at a moment; null = it did not exist then. */
	function linesAtKey(id: string, k: TKey): AssemblyLine[] | null {
		if (k.d === NOW.d) return getAssembly(id)?.lines ?? null;
		const st = statesOf(id);
		let cur: (typeof st)[number] | null = null;
		for (const s of st) if (keyLE({ d: s.d, s: s.s }, k)) cur = s;
		if (cur) return cur.lines;
		if (st.length) return null;
		// No recorded change anywhere in history — it has always been what it is.
		return getAssembly(id)?.lines ?? null;
	}
	function timeRows(id: string, a: TKey, b: TKey): DiffRow[] {
		return diffLines((linesAtKey(id, a) ?? []) as AssemblySnapshotLine[], (linesAtKey(id, b) ?? []) as AssemblySnapshotLine[]);
	}
	const isAsmish = (id: string) => !!getAssembly(id) || !!eraAsm[id];
	/** Did anything at or below this node move between the two moments? Drives
	 *  the default expansion: changed branches open, quiet ones stay folded. */
	const changedMemo = new Map<string, boolean>();
	function subtreeChanged(id: string, a: TKey, b: TKey): boolean {
		const key = `${id}|${a.d},${a.s}|${b.d},${b.s}`;
		const hit = changedMemo.get(key);
		if (hit !== undefined) return hit;
		changedMemo.set(key, false); // cycle guard; real value written below
		const rows = timeRows(id, a, b);
		let changed = rows.some((r) => r.kind !== 'same');
		if (!changed) changed = rows.some((r) => isAsmish(r.id) && subtreeChanged(r.id, a, b));
		changedMemo.set(key, changed);
		return changed;
	}
	/** Open the tree at an event's moment. Recorded revisions map onto the era
	 *  timeline when they fall inside it; otherwise the moment is the end of
	 *  their day. */
	function viewEvent(e: HistoryEvent, mode: TimeMode) {
		if (!e.date) return;
		let s: number;
		let exact = true;
		const sig = (ls: AssemblyLine[] | null | undefined) =>
			JSON.stringify((ls ?? []).map((l) => `${l.part ?? l.assembly}|${l.qty}`).sort());
		if (e.seq !== undefined && e.kind !== 'revision' && e.kind !== 'tag') {
			s = e.seq; // reconstructed events carry their commit's seq
		} else if (e.kind === 'revision' && e.seq !== undefined && e.date >= eraThrough) {
			// The entry's state is in statesOf at its own seq. If the era's last
			// recorded state for this node is the SAME state — the stamp merged
			// before the artifact froze — stand at the era commit instead, so
			// "before" lands just ahead of the change rather than after it.
			s = e.seq;
			const tl = eraAsm[e.node]?.timeline ?? [];
			const last = tl[tl.length - 1];
			if (last?.date === e.date && sig(last.lines) === sig(linesAtKey(e.node, { d: e.date, s }))) s = last.seq;
		} else {
			// A recorded revision from inside the era, or a tag: find its commit.
			const hit =
				(e.commit ? eraCommits[e.commit]?.seq : undefined) ??
				eraAsm[e.node]?.timeline.find((t) => t.date === e.date)?.seq;
			if (hit !== undefined) s = hit;
			else {
				s = DAY_END; // end of the day; "before" is then its start
				exact = false;
			}
		}
		const ref = e.tag ? e.tag.name : e.pr ? `#${e.pr}` : (e.version ?? e.commit ?? '');
		timeView = {
			point: { d: e.date, s },
			before: exact ? { d: e.date, s: s - 1 } : { d: e.date, s: -1 },
			label: `${memberName(e.node)} ${ref} · ${fmtDate(e.date)}`,
			mode
		};
	}

	// Clicking a thumbnail in the tree opens the same detail view the other tabs use:
	// printed parts get the parts-dashboard modal (3D viewer, versions, plates);
	// off-the-shelf items get the hardware modal (specs, where it goes, sourcing).
	let partOpen = $state(false);
	let partModal = $state<Part | null>(null);
	// the modal is controlled: seed its preview colour + newest version on open
	let partColor = $state('ash-gray');
	let partVersion = $state<PartVersion | null>(null);
	function openPart(p: Part) {
		partModal = p;
		partColor = primaryColorId(p, colorStore.roles) ?? 'ash-gray';
		partVersion = p.versions?.[p.versions.length - 1] ?? null;
		partOpen = true;
	}
	let hwOpen = $state(false);
	let hwModal = $state<Hardware | null>(null);
	function openHardware(h: Hardware) {
		hwModal = h;
		hwOpen = true;
	}
	// A node's name pulls it out of the tree into the same one-box view the parts
	// dashboard opens, which is the point of having the view at all: on this page
	// an assembly is a branch among hundreds, and sometimes you want just the box.
	let asmOpen = $state(false);
	let asmId = $state<string | null>(null);
	function openAssembly(id: string) {
		asmId = id;
		asmOpen = true;
	}

	// The whole tree flattened, one row per node, with STL/DXF links on anything
	// downloadable — an indented BOM that survives being sorted or filtered.
	function downloadCsv() {
		const spec = exportSpec(layers);
		download(filename(spec, 'assembly-tree'), assemblyCsv('machine', spec));
	}
</script>

<svelte:window onclick={onWindowClick} onkeydown={onWindowKey} />

<Seo title="Machine assembly" description="The Sorter V2 machine's assembly tree." />

{#snippet requiresRows(partId: string, mult: number)}
	{@const part = getPart(partId)}
	{#each part?.requires ?? [] as req (req.part)}
		{@const hw = getHardware(req.part)}
		{#if hw}
			{@const img = hardwareImage(hw)}
			<div class="mt-2 flex items-center gap-3 border border-border bg-[var(--color-bg)] p-2">
				{#if img}
					<button type="button" class="asm-thumb shrink-0" title="View {hw.name} details" onclick={() => openHardware(hw)}>
						<img src={img.src} alt={hw.name} class="h-10 w-10 object-contain" />
					</button>
				{/if}
				<div class="min-w-0 flex-1">
					<div class="flex items-center gap-1.5 text-xs font-semibold text-text">
						<HardwareIcon {hw} size={14} /><span class="truncate">{hw.name}</span>
						<AlternativeBadge value={hw.alternative} size={14} />
						<ConflictBadge conflicts={hw.conflicts} size={14} />
					</div>
				</div>
				<div class="text-right text-xs tabular-nums text-text">
					<div class="font-semibold">×{req.qty} each</div>
					{#if mult > 1}<div class="text-text-muted">{req.qty * mult} total</div>{/if}
				</div>
			</div>
		{/if}
	{/each}
{/snippet}

<!-- One off-the-shelf line of an assembly: the screws, nuts and bought components
     that belong to the joint rather than to either part it holds together. -->
{#snippet hardwareRow(hw: Hardware, each: number, total: number)}
	{@const img = hardwareImage(hw)}
	<div data-member={hw.id} class="ml-1.5 mt-2 flex items-center gap-3 border border-border bg-[var(--color-bg)] p-2 sm:ml-4">
		{#if img}
			<button type="button" class="asm-thumb shrink-0" title="View {hw.name} details" onclick={() => openHardware(hw)}>
				<img src={img.src} alt={hw.name} class="h-8 w-8 object-contain" />
			</button>
		{/if}
		<div class="flex min-w-0 flex-1 items-center gap-1.5 text-xs font-semibold text-text">
			<HardwareIcon {hw} size={14} /><span class="truncate">{hw.name}</span>
			<AlternativeBadge value={hw.alternative} size={14} />
						<ConflictBadge conflicts={hw.conflicts} size={14} />
			{@render tagChips(hw.id)}
		</div>
		<div class="text-right text-xs tabular-nums text-text">
			<div class="font-semibold">×{each}</div>
			{#if total !== each}<div class="text-text-muted">{total} total</div>{/if}
		</div>
	</div>
{/snippet}

<!-- how a set of lines becomes one unit — soldered, self-tapped, friction-held -->
{#snippet joiningRows(list: Joining[] | undefined)}
	{#each list ?? [] as j (j.method)}
		<div class="mt-1 flex max-w-2xl flex-wrap items-baseline gap-x-2">
			<Badge variant="warning"><Zap size={10} />{JOIN_LABELS[j.method]}</Badge>
			{#if j.note}<AssemblyDescription text={j.note} as="span" class="text-xs text-text-muted" />{/if}
		</div>
	{/each}
{/snippet}


<!-- The tags standing on a node's current version, as badges: STABLE (green)
     or EXPERIMENTAL, with a count when several. Hover names the tags. -->
{#snippet tagChips(id: string)}
	{@const tags = tagsFor(id)}
	{#each [['golden', 'border-warning/70 text-warning-dark'], ['stable', 'border-success/60 text-success-dark'], ['experimental', 'border-border text-text-muted']] as [st, cls] (st)}
		{@const n = tags.filter((t) => t.stability === st)}
		{#if n.length}
			<span
				class="border px-1 py-px text-[10px] font-semibold uppercase tracking-wider {cls}"
				title={n.map((t) => t.name).join(', ')}>{st}{n.length > 1 ? ` ×${n.length}` : ''}</span>
		{/if}
	{/each}
{/snippet}

{#snippet lines(list: AssemblyLine[], mult: number, depth: number, endpoints: Set<string> | null = null)}
	<!-- Keyed by position as well as id: two lines can legitimately name the
	     same part, and a bare id key makes that a duplicate-key error that
	     blanks the whole page on hydration. -->
	{#each order === 'name' ? [...list].sort((a, b) => memberName(a.part ?? a.assembly ?? '').localeCompare(memberName(b.part ?? b.assembly ?? ''))) : list as line, i (`${line.part ?? line.assembly}-${i}`)}
		{#if !lineShown(line)}
			<!-- filtered out -->
		{:else if line.assembly}
			{@render node(line.assembly, line.qty, lineQty(line, layers) * mult, depth + 1, endpoints?.has(line.assembly) ?? false)}
		{:else if line.part && getLasercut(line.part)}
			{@const lc = getLasercut(line.part)!}
			<div data-member={line.part} class="ml-1.5 mt-2 flex items-center gap-3 border border-border bg-surface p-2 sm:ml-4 sm:p-3">
				<img src={lc.preview} alt={lc.name} class="h-12 w-12 shrink-0 object-contain" />
				<div class="min-w-0 flex-1">
					<div class="flex flex-wrap items-baseline gap-x-2">
						<span class="text-sm font-semibold text-text">{lc.name}</span>
						<span class="border border-border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-text-muted"
							>laser cut</span>
					</div>
					<div class="text-xs text-text-muted">{lc.thicknessIn} plywood · {lc.widthMm}×{lc.heightMm} mm</div>
				</div>
				<div class="text-right text-xs font-semibold tabular-nums text-text">×{lineQty(line, layers)}</div>
			</div>
		{:else if line.part && getHardware(line.part)}
			{@render hardwareRow(
				getHardware(line.part)!,
				lineQty(line, layers),
				lineQty(line, layers) * mult
			)}
		{:else if line.part}
			{@const part = getPart(line.part)}
			{#if part}
				{@const total = lineQty(line, layers) * mult}
				<div data-member={line.part} class="ml-1.5 mt-2 border border-border bg-surface p-2 sm:ml-4 sm:p-3">
					<div class="flex items-center gap-3">
						<button type="button" class="asm-thumb shrink-0" title="View {part.name} details" onclick={() => openPart(part)}>
							<img src={part.render} alt={part.name} class="h-12 w-12 object-contain" />
						</button>
						<div class="min-w-0 flex-1">
							<div class="flex flex-wrap items-baseline gap-x-2">
								<span class="text-sm font-semibold text-text">{part.name}</span>
								<span class="border border-border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-text-muted"
									>3D printed</span>
								{#if line.part}{@render tagChips(line.part)}{/if}
							</div>
							<div class="text-xs text-text-muted">{part.grams.toFixed(0)} g each</div>
						</div>
						<div class="text-right text-xs tabular-nums text-text">
							<div class="font-semibold">×{lineQty(line, layers)}</div>
							{#if total !== lineQty(line, layers)}<div class="text-text-muted">{total} total</div>{/if}
						</div>
					</div>
					{@render requiresRows(line.part, total)}
				</div>
			{/if}
		{/if}
	{/each}
{/snippet}

<!-- One member of a version snapshot or diff row: name, kind, pinned uid and
     the member revision that uid names. -->
{#snippet memberCell(id: string, uid: string | undefined, struck: boolean)}
	{@const render = getPart(id)?.render}
	{#if render}<img src={render} alt="" class="h-7 w-7 shrink-0 object-contain {struck ? 'opacity-50' : ''}" />{/if}
	<span class="min-w-0 flex-1">
		<span class="font-semibold text-text {struck ? 'line-through opacity-60' : ''}">{memberName(id)}</span>
		{#if getAssembly(id)}<span class="ml-1 border border-border px-1 py-px text-[9px] font-semibold uppercase tracking-wider text-text-muted">assembly</span>{/if}
		{#if uid}
			<span class="ml-1.5 font-mono text-[11px] text-text-muted">{uid}</span>
			{#if memberRev(id, uid)}<span class="text-[11px] text-text-muted"> · v{memberRev(id, uid)}</span>{/if}
		{/if}
	</span>
{/snippet}

<!-- A snapshot line rendered in the same style as the live rows, so an old
     version reads like the assembly did then — down to the archived render
     and grams of the pinned revision, when they were recorded. -->
{#snippet snapshotRow(l: AssemblySnapshotLine, mult: number)}
	{@const id = l.part ?? l.assembly ?? ''}
	{@const part = getPart(id)}
	{@const hw = getHardware(id)}
	{@const qtyN = typeof l.qty === 'number' ? l.qty : null}
	{@const total = qtyN === null ? null : qtyN * mult}
	{@const rev = memberRev(id, l.uid)}
	{@const pv = part?.versions?.find((v) => v.uid === l.uid)}
	{#if part || getAssembly(id)}
		<div class="ml-1.5 mt-2 border border-border bg-surface p-2 sm:ml-4 sm:p-3">
			<div class="flex items-center gap-3">
				{#if part}
					<img src={pv?.render ?? part.render} alt={part.name} class="h-12 w-12 shrink-0 object-contain" />
				{/if}
				<div class="min-w-0 flex-1">
					<div class="flex flex-wrap items-baseline gap-x-2">
						<span class="text-sm font-semibold text-text">{memberName(id)}</span>
						<span class="border border-border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-text-muted"
							>{part ? '3D printed' : 'assembly'}</span>
						{#if l.uid}
							<span class="font-mono text-xs text-text-muted">{l.uid}</span>{#if rev}<span class="text-xs text-text-muted">· v{rev}</span>{/if}
						{/if}
					</div>
					{#if part && typeof (pv?.grams ?? part.grams) === 'number'}
						<div class="text-xs text-text-muted">{(pv?.grams ?? part.grams).toFixed(0)} g each</div>
					{/if}
				</div>
				<div class="text-right text-xs tabular-nums text-text">
					<div class="font-semibold">×{l.qty}</div>
					{#if total !== null && total !== qtyN}<div class="text-text-muted">{total} total</div>{/if}
				</div>
			</div>
		</div>
	{:else}
		{@const img = hw ? hardwareImage(hw) : null}
		<div class="ml-1.5 mt-2 flex items-center gap-3 border border-border bg-[var(--color-bg)] p-2 sm:ml-4">
			{#if img}<img src={img.src} alt={hw?.name} class="h-8 w-8 shrink-0 object-contain" />{/if}
			<div class="flex min-w-0 flex-1 items-center gap-1.5 text-xs font-semibold text-text">
				{#if hw}<HardwareIcon {hw} size={14} />{/if}<span class="truncate">{memberName(id)}</span>
				{#if l.uid}<span class="font-mono font-normal text-text-muted">{l.uid}</span>{/if}
			</div>
			<div class="text-right text-xs tabular-nums text-text">
				<div class="font-semibold">×{l.qty}</div>
				{#if total !== null && total !== qtyN}<div class="text-text-muted">{total} total</div>{/if}
			</div>
		</div>
	{/if}
{/snippet}

<!-- One side of a diff row. Absent = the member doesn't exist in this
     version; a dashed placeholder keeps the two columns aligned. -->
{#snippet diffCell(l: AssemblySnapshotLine | undefined, tone: 'plain' | 'danger' | 'success')}
	{#if l}
		<div
			class="flex items-center gap-2 border px-2 py-1.5 text-xs {tone === 'danger'
				? 'border-danger/50 bg-danger/[0.06]'
				: tone === 'success'
					? 'border-success/50 bg-success/[0.07]'
					: 'border-border bg-surface'}"
		>
			{@render memberCell(l.part ?? l.assembly ?? '', l.uid, false)}
			<span class="shrink-0 tabular-nums {tone === 'plain' ? 'text-text-muted' : 'font-semibold'} {tone === 'danger' ? 'text-danger-dark' : tone === 'success' ? 'text-success-dark' : ''}">×{l.qty}</span>
		</div>
	{:else}
		<div class="border border-dashed border-border/70"></div>
	{/if}
{/snippet}

<!-- A node's line rows, routed by the header's version controls: the live
     lines, one version's snapshot, or the diff between two versions. -->
{#snippet versionSwitch(asm: Assembly, mult: number, depth: number)}
	{@const cur = currentVersion(asm)}
	{@const shown = filtering ? cur : (shownVersion[asm.id] ?? cur)}
	{@const base = filtering ? undefined : diffBase[asm.id]}
	{#if base && base !== shown}
		{@const [lo, hi] = Number(base) <= Number(shown) ? [base, shown] : [shown, base]}
		{@const loEntry = asm.versions?.find((e) => e.version === lo)}
		<div class="ml-1.5 mt-2 sm:ml-4">
			<div class="grid grid-cols-2 gap-x-1.5 gap-y-1">
				<div class="flex items-baseline gap-1.5 border-b border-danger/60 px-2 pb-1 text-xs">
					<span class="font-semibold text-danger">v{lo}</span>
					<span class="text-text-muted">{lo === cur ? 'current' : `superseded${loEntry?.date ? ` ${fmtDate(loEntry.date)}` : ''}`}</span>
				</div>
				<div class="flex items-baseline gap-1.5 border-b border-success/60 px-2 pb-1 text-xs">
					<span class="font-semibold text-success">v{hi}</span>
					<span class="text-text-muted">{hi === cur ? 'current' : 'superseded'}</span>
				</div>
				{#each diffLines(linesAt(asm, lo) ?? [], linesAt(asm, hi) ?? []) as r (r.id)}
					{@render diffCell(r.kind === 'added' ? undefined : r.old, r.kind === 'same' ? 'plain' : 'danger')}
					{@render diffCell(r.kind === 'removed' ? undefined : r.now, r.kind === 'same' ? 'plain' : 'success')}
				{/each}
			</div>
		</div>
	{:else if shown !== cur}
		{@const entry = asm.versions?.find((e) => e.version === shown)}
		<div class="ml-1.5 mt-2 sm:ml-4">
			<div class="flex flex-wrap items-center gap-x-2 gap-y-1 border border-warning/50 bg-warning/[0.08] px-2 py-1.5 text-xs text-warning-dark">
				<History size={11} /> v{shown}, superseded{entry?.date ? ` ${fmtDate(entry.date)}` : ''}
				{#if entry?.uid}<span class="font-mono">{entry.uid}</span>{/if}
				<button type="button" class="ml-auto font-medium underline underline-offset-2" onclick={() => delete shownVersion[asm.id]}>back to v{cur}</button>
			</div>
			{#if entry?.message}<AssemblyDescription text={entry.message} class="mt-1 max-w-2xl text-xs text-text-muted" />{/if}
			{#if entry?.lines?.length}
				{#each entry.lines as l, i (`${l.part ?? l.assembly}-${i}`)}
					{@render snapshotRow(l, mult)}
				{/each}
			{:else if entry?.lines}
				<p class="mt-1.5 text-xs italic text-text-muted">Nothing was recorded in this version.</p>
			{:else}
				<p class="mt-1.5 text-xs italic text-text-muted">This version's lines were not snapshotted.</p>
			{/if}
		</div>
	{:else}
		{@render joiningRows(asm.joining)}
		<!-- assemblies a brace wires into get a box, so the tick lands on a
		     visible container instead of ending in space -->
		{@const eps = asm.connections?.length ? new Set(asm.connections.flatMap((c) => [c.from, c.to])) : null}
		{@render lines(asm.lines ?? [], mult, depth, eps)}
	{/if}
{/snippet}

<!-- The subtree's timeline, newest first. One line per moment: when, which
     node, what happened, the PR it came from. The whole row is a button —
     clicking it renders the tree below at that moment with the change diffed
     in; "vs now" diffs that moment against the current tree. Tags are
     highlighted rows on the same timeline. -->
{#snippet historyPanel(asm: Assembly)}
	{@const events = historyOf(asm.id)}
	<div class="ml-1.5 mt-2 border border-border bg-surface sm:ml-4">
		<div class="flex items-center gap-1.5 border-b border-border px-2.5 py-1.5 text-xs">
			<History size={11} class="shrink-0 text-text-muted" />
			<span class="font-semibold text-text">History</span>
			<span class="text-text-muted">
				— {events.length} change{events.length === 1 ? '' : 's'} to anything under this node · click one to see the tree then
			</span>
			<button
				type="button"
				class="ml-auto flex h-5 w-5 items-center justify-center text-text-muted hover:text-text"
				onclick={() => delete historyFor[asm.id]}
				aria-label="Close history"
			>
				<X size={12} />
			</button>
		</div>
		{#each events as e, i (i)}
			{@const clickable = !!e.date}
			<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
			<div
				class="flex items-baseline gap-x-2 border-b border-border/60 px-2.5 py-1 text-xs last:border-b-0 {e.kind === 'tag'
					? 'bg-primary/[0.05]'
					: ''} {clickable ? 'cursor-pointer hover:bg-primary/[0.04]' : ''}"
				role={clickable ? 'button' : undefined}
				tabindex={clickable ? 0 : undefined}
				onclick={(ev) => {
					if (!clickable || (ev.target as Element).closest('a, button')) return;
					viewEvent(e, e.kind === 'tag' ? 'tree' : 'change');
				}}
				onkeydown={(ev) => {
					if (clickable && ev.target === ev.currentTarget && (ev.key === 'Enter' || ev.key === ' ')) {
						ev.preventDefault();
						viewEvent(e, e.kind === 'tag' ? 'tree' : 'change');
					}
				}}
			>
				<span class="w-20 shrink-0 whitespace-nowrap tabular-nums text-text-muted">{e.date ? fmtDate(e.date) : '—'}</span>
				{#if e.tag}
					<span class="shrink-0 border px-1 py-px text-[10px] font-semibold uppercase tracking-wider {e.tag.stability === 'stable' ? 'border-success/60 text-success-dark' : 'border-border text-text-muted'}">{e.tag.stability}</span>
					<span class="shrink-0 font-semibold text-text">{e.tag.name}</span>
				{/if}
				{#if memberOf(e.node)}
					<button type="button" class="shrink-0 font-semibold text-text hover:text-primary" onclick={() => openNode(e.node)}>{memberName(e.node)}</button>
				{:else}
					<span class="shrink-0 font-semibold text-text-muted line-through">{memberName(e.node)}</span>
				{/if}
				{#if e.version}<span class="shrink-0 font-semibold text-text">{e.version}</span>{/if}
				{#if KIND_LABEL[e.kind]}<span class="shrink-0 text-text-muted">{KIND_LABEL[e.kind]}</span>{/if}
				{#if e.breaking}<span class="shrink-0 border border-danger/50 px-1 py-px text-[10px] font-semibold uppercase tracking-wider text-danger">breaking</span>{/if}
				<span class="min-w-0 flex-1 truncate">
					{#if e.detail}<span class="text-text">{e.detail}</span>{/if}
					{#if e.message}<span class="text-text-muted">{e.message}</span>{/if}
				</span>
				{#if clickable}
					<button type="button" class="shrink-0 text-text-muted hover:text-text" onclick={() => viewEvent(e, 'vs-now')}>vs now</button>
				{/if}
				{#if e.pr}
					<a class="shrink-0 text-primary hover:text-primary-hover" href="{prBase}{e.pr}" target="_blank" rel="noopener">#{e.pr}</a>
				{:else if commitUrl(e.commit)}
					<a class="shrink-0 font-mono text-[11px] text-primary hover:text-primary-hover" href={commitUrl(e.commit)} target="_blank" rel="noopener">{e.commit}</a>
				{/if}
			</div>
		{/each}
	</div>
{/snippet}

<!-- One non-assembly member in the time tree: green when the window added it,
     red when it removed it, plain otherwise; a qty change shows both counts. -->
{#snippet timePartRow(r: DiffRow)}
	<div class="ml-1.5 mt-1 sm:ml-4">
		{#if r.kind === 'qty'}
			<div class="flex items-center gap-2 border border-border bg-surface px-2 py-1.5 text-xs">
				{@render memberCell(r.id, r.now?.uid, false)}
				<span class="shrink-0 tabular-nums"><span class="font-semibold text-danger-dark">×{r.old?.qty}</span><span class="text-text-muted">→</span><span class="font-semibold text-success-dark">×{r.now?.qty}</span></span>
			</div>
		{:else}
			{@render diffCell(r.now ?? r.old, r.kind === 'added' ? 'success' : r.kind === 'removed' ? 'danger' : 'plain')}
		{/if}
	</div>
{/snippet}

<!-- The tree between two moments. Each assembly renders the diff of its lines
     at the two keys; an added/removed branch renders plain inside its tint
     (its own window collapses to the side it exists on). Changed branches
     start open, quiet ones folded. -->
{#snippet timeNode(id: string, row: DiffRow | null, depth: number, a: TKey, b: TKey)}
	{@const kind = row?.kind ?? 'same'}
	{@const ca = kind === 'added' ? b : a}
	{@const cb = kind === 'removed' ? a : b}
	{@const rows = timeRows(id, ca, cb)}
	{@const nm = memberName(id)}
	{@const open = rows.length > 0 && (expanded[id] ?? (depth === 0 || subtreeChanged(id, ca, cb)))}
	<div id="asm-{id}" class="{depth > 0 ? 'ml-1.5 mt-2 sm:ml-4' : ''} py-1">
		<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
		<div
			class="-mx-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 px-1 py-0.5 {rows.length
				? 'cursor-pointer hover:bg-primary/[0.04]'
				: ''} {kind === 'added' ? 'bg-success/[0.06]' : kind === 'removed' ? 'bg-danger/[0.06]' : ''}"
			role={rows.length ? 'button' : undefined}
			tabindex={rows.length ? 0 : undefined}
			aria-expanded={rows.length ? open : undefined}
			onclick={(e) => {
				if (!rows.length || (e.target as Element).closest('a, button')) return;
				expanded[id] = !open;
			}}
			onkeydown={(e) => {
				if (!rows.length || e.target !== e.currentTarget) return;
				if (e.key === 'Enter' || e.key === ' ') {
					e.preventDefault();
					expanded[id] = !open;
				}
			}}
		>
			<span class="flex h-5 w-5 shrink-0 items-center justify-center text-text-muted" aria-hidden="true">
				{#if rows.length}
					{#if open}<ChevronDown size={14} />{:else}<ChevronRight size={14} />{/if}
				{/if}
			</span>
			<span class="text-sm font-medium {kind === 'removed' ? 'text-danger-dark line-through' : kind === 'added' ? 'text-success-dark' : 'text-text'}">{nm}</span>
			{#if kind === 'qty'}
				<span class="text-xs tabular-nums"><span class="font-semibold text-danger-dark">×{row?.old?.qty}</span><span class="text-text-muted">→</span><span class="font-semibold text-success-dark">×{row?.now?.qty}</span></span>
			{:else if row && row.now?.qty !== 1 && row.now?.qty !== undefined}
				<span class="text-xs tabular-nums text-text-muted">×{row.now.qty}</span>
			{:else if row && kind === 'removed' && row.old?.qty !== 1}
				<span class="text-xs tabular-nums text-text-muted">×{row.old?.qty}</span>
			{/if}
			{#if kind === 'added'}<span class="border border-success/60 px-1 py-px text-[10px] font-semibold uppercase tracking-wider text-success-dark">added</span>{/if}
			{#if kind === 'removed'}<span class="border border-danger/50 px-1 py-px text-[10px] font-semibold uppercase tracking-wider text-danger">removed</span>{/if}
		</div>
		{#if historyFor[id]}{@render historyPanel(getAssembly(id) ?? ({ id, name: nm } as Assembly))}{/if}
		{#if open}
			<div class="tree-branch relative pl-2 sm:pl-4">
				<button type="button" class="tree-line" onclick={() => (expanded[id] = false)} aria-label="Collapse {nm}"></button>
				{#each rows as r (r.id)}
					{#if isAsmish(r.id)}
						{@render timeNode(r.id, r, depth + 1, ca, cb)}
					{:else}
						{@render timePartRow(r)}
					{/if}
				{/each}
			</div>
		{/if}
	</div>
{/snippet}

{#snippet node(id: string, qty: AssemblyLine['qty'], mult: number, depth: number, boxed: boolean = false)}
	{@const asm = getAssembly(id)}
	{#if asm && (!filtering || keep.assemblies.has(asm.id))}
		{@const hasContent =
			(asm.lines?.length ?? 0) > 0 ||
			(asm.candidates?.length ?? 0) > 0 ||
			(asm.versions?.length ?? 1) > 1 ||
			(asm.joining?.length ?? 0) > 0 ||
			(asm.images?.length ?? 0) > 0}
		{@const open = hasContent && isOpen(asm.id)}
		<div
			id="asm-{asm.id}"
			data-member={asm.id}
			class="{depth > 0 ? 'ml-1.5 mt-2 sm:ml-4' : ''} py-1 {boxed ? 'border border-border px-1.5' : ''} {focus === asm.id ? 'bg-primary/[0.06]' : ''}"
		>
			<!-- The whole row is the expand/collapse target; anything interactive
			     inside it (details, guide link, ⋮ menu) is filtered out by the
			     closest() check so a click on those doesn't also fold the node.
			     role/tabindex/keydown are all present when hasContent makes it
			     interactive; the compiler can't see through the conditional. -->
			<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
			<div
				class="-mx-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 px-1 py-0.5 {hasContent
					? 'cursor-pointer hover:bg-primary/[0.04]'
					: ''}"
				role={hasContent ? 'button' : undefined}
				tabindex={hasContent ? 0 : undefined}
				aria-expanded={hasContent ? open : undefined}
				aria-label={hasContent ? `${open ? 'Collapse' : 'Expand'} ${asm.name}` : undefined}
				onclick={(e) => {
					if (!hasContent || (e.target as Element).closest('a, button')) return;
					toggle(asm.id);
				}}
				onkeydown={(e) => {
					if (!hasContent || e.target !== e.currentTarget) return;
					if (e.key === 'Enter' || e.key === ' ') {
						e.preventDefault();
						toggle(asm.id);
					}
				}}
			>
				<span class="flex h-5 w-5 shrink-0 items-center justify-center text-text-muted" aria-hidden="true">
					{#if hasContent}
						{#if open}<ChevronDown size={14} />{:else}<ChevronRight size={14} />{/if}
					{/if}
				</span>
				<span class="text-sm font-medium text-text">{asm.name}</span>
				<button
					type="button"
					class="flex h-5 w-5 items-center justify-center text-text-muted hover:text-primary"
					onclick={() => openAssembly(asm.id)}
					title="View {asm.name} details"
					aria-label="View {asm.name} details"
				>
					<Info size={13} />
				</button>
				<span class="text-xs tabular-nums text-text-muted">
					{#if qty === 'per-layer'}×{layers} (1 per layer)
					{:else if qty === 'middle-layers'}×{Math.max(0, layers - 2)} (layers between the interfaces)
					{:else if qty !== 1}×{qty}{/if}
				</span>
				{@render tagChips(asm.id)}
				{#if asm.status === 'stub'}
					<span
						class="cursor-help border border-border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-text-muted"
						title={STATUS_NOTE.stub}>stub — not yet detailed</span>
				{/if}
				<span class="relative ml-auto flex items-center gap-3" data-asm-menu>
					<!-- The docs site is where the step-by-step build lives; this node is only
					     the bill of materials for it. Link out when a page exists. -->
					{#if docsUrl(asm)}
						<a
							href={docsUrl(asm)}
							target="_blank"
							rel="noopener"
							class="inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-hover"
						>
							In Docs <ExternalLink size={10} />
						</a>
					{/if}
					{#if !filtering && (asm.versions?.length ?? 0) > 1}
						{#if diffBase[asm.id]}
							<button
								type="button"
								class="inline-flex items-center gap-1 border border-border bg-surface px-1.5 py-0.5 text-xs text-text hover:border-primary"
								onclick={() => delete diffBase[asm.id]}
								title="Close the diff"
							>
								diff v{diffBase[asm.id]} <X size={11} />
							</button>
						{:else}
							<DropdownMenu label="{asm.name}: diff against a version" menuClass="w-48">
								{#snippet trigger({ toggle, open })}
									<button
										type="button"
										class="inline-flex items-center gap-0.5 text-xs text-text-muted hover:text-text"
										onclick={toggle}
										aria-expanded={open}
									>
										Diff against <ChevronDown size={11} />
									</button>
								{/snippet}
								{#snippet children({ close })}
									{#each [...(asm.versions ?? [])].reverse() as v (v.version)}
										{#if v.version !== (shownVersion[asm.id] ?? currentVersion(asm))}
											<button
												type="button"
												class="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs hover:bg-[var(--color-bg)]"
												onclick={() => {
													diffBase[asm.id] = v.version;
													close();
												}}
											>
												<span>v{v.version}</span>
												<span class="text-text-muted">{v.version === currentVersion(asm) ? 'current' : `superseded${v.date ? ` ${fmtDate(v.date)}` : ''}`}</span>
											</button>
										{/if}
									{/each}
								{/snippet}
							</DropdownMenu>
						{/if}
						<DropdownMenu label="{asm.name}: version to display" menuClass="w-52">
							{#snippet trigger({ toggle, open })}
								{@const viewingOld = !!shownVersion[asm.id] && shownVersion[asm.id] !== currentVersion(asm)}
								<button
									type="button"
									class="inline-flex items-center gap-1 border px-1.5 py-0.5 text-xs {viewingOld
										? 'border-warning/50 bg-warning/[0.08] text-warning-dark hover:border-warning'
										: 'border-border bg-surface text-text hover:border-primary'}"
									onclick={toggle}
									aria-expanded={open}
								>
									{viewingOld
									? `Viewing v${shownVersion[asm.id]} (superseded)`
									: `Viewing v${currentVersion(asm)} (current)`} <ChevronDown size={11} />
								</button>
							{/snippet}
							{#snippet children({ close })}
								{#each [...(asm.versions ?? [])].reverse() as v (v.version)}
									{@const active = v.version === (shownVersion[asm.id] ?? currentVersion(asm))}
									<button
										type="button"
										class="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs hover:bg-[var(--color-bg)]"
										onclick={() => {
											if (v.version === currentVersion(asm)) delete shownVersion[asm.id];
											else shownVersion[asm.id] = v.version;
											close();
										}}
									>
										<span>v{v.version}</span>
										<span class="text-text-muted">{v.version === currentVersion(asm) ? 'current' : `superseded${v.date ? ` ${fmtDate(v.date)}` : ''}`}</span>
										{#if active}<Check size={12} class="ml-auto text-primary" />{/if}
									</button>
								{/each}
							{/snippet}
						</DropdownMenu>
					{:else}
						<span class="text-xs text-text-muted">v{currentVersion(asm)}</span>
					{/if}
					{#if hasContent}
						<button
							type="button"
							class="flex h-5 w-5 items-center justify-center text-text-muted hover:text-text"
							aria-label="More actions for {asm.name}"
							aria-expanded={menuFor === asm.id}
							onclick={() => (menuFor = menuFor === asm.id ? null : asm.id)}
						>
							<EllipsisVertical size={14} />
						</button>
						{#if menuFor === asm.id}
							<div class="setup-panel absolute right-0 top-6 z-30 w-40 py-1 text-xs" role="menu">
								<button type="button" role="menuitem" class="block w-full px-3 py-1.5 text-left text-text hover:bg-primary/[0.06]" onclick={() => setSubtree(asm.id, true)}>Expand all</button>
								<button type="button" role="menuitem" class="block w-full px-3 py-1.5 text-left text-text hover:bg-primary/[0.06]" onclick={() => setSubtree(asm.id, false)}>Collapse all</button>
								<button
									type="button"
									role="menuitem"
									class="block w-full px-3 py-1.5 text-left text-text hover:bg-primary/[0.06]"
									onclick={() => {
										historyFor[asm.id] = true;
										expanded[asm.id] = true;
										menuFor = null;
									}}>History</button>
							</div>
						{/if}
					{/if}
				</span>
			</div>
			<!-- The description is NOT rendered here on purpose: it lives in the
			     detail view the ⓘ opens. Inline it turns the tree into a wall of
			     prose that restates the line rows below it. -->
			{#if open}
			{@const braceGutter =
				asm.connections?.length && !filtering
					? 32 + (braceGroups(asm.connections).length - 1) * 16
					: 0}
			<div
				class="tree-branch relative pl-2 sm:pl-4"
				style={braceGutter ? `padding-right: ${braceGutter}px` : undefined}
			>
				<button type="button" class="tree-line" onclick={() => toggle(asm.id)} aria-label="Collapse {asm.name}"></button>
				{#if braceGutter && asm.connections}
					<ConnectionBraces edges={asm.connections} gutter={braceGutter} labelOf={(m) => CONN_LABELS[m] ?? m} nameOf={memberName} travelOf={(id) => screwTravel(getHardware(id))} />
				{/if}
			{#if asm.images?.length}<div class="mt-2"><ImageStrip images={asm.images} /></div>{/if}
			{#if historyFor[asm.id] && !filtering}{@render historyPanel(asm)}{/if}
			{@render versionSwitch(asm, mult, depth)}
			<!-- Alternative bills of materials under test, rendered with the same
			     line rows. -->
			{#each (filtering ? [] : (asm.candidates ?? [])) as c (c.uid)}
				{@const retired = !!(c.superseded_by || c.rejected_at)}
				<div class="ml-1.5 mt-3 border border-dashed p-2 sm:ml-4 sm:p-3 {retired ? 'border-border opacity-60' : 'border-primary/60'}">
					<div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
						<span class="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-primary"><FlaskConical size={11} /> Candidate</span>
						{#if c.name}<span class="text-sm font-semibold text-text">{c.name}</span>{/if}
						<span class="font-mono text-xs text-text">{c.uid}</span>
						<span class="text-xs text-text-muted">· {fmtDate(c.created_at)}</span>
						{#if retired}<span class="border border-border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-text-muted">{c.rejected_at ? 'rejected' : 'superseded'}</span>{/if}
					</div>
					<AssemblyDescription text={c.message} class="mt-0.5 max-w-2xl text-xs text-text-muted" />
					{#if c.images?.length}<div class="mt-2"><ImageStrip images={c.images} /></div>{/if}
					{@render joiningRows(c.joining)}
					<p class="mt-1 text-xs italic text-text-muted/70">An alternative bill of materials under test — not part of the build and not in the totals.</p>
					{@render lines(c.lines, mult, depth)}
				</div>
			{/each}
			</div>
			{/if}
		</div>
	{/if}
{/snippet}

<!-- Wider than the other tabs on purpose: nested nodes each reserve a right
     gutter for their connection braces, and the rows need the room back. -->
<div class="mx-auto max-w-screen-2xl px-4 py-8 sm:px-6">
	<header class="mb-5">
		<h1 class="text-2xl font-bold text-text">Machine assembly</h1>
	</header>

	<div class="mb-6"><LayerControl /></div>

	<section class="min-w-0">
			<div class="mb-4 flex items-center gap-3">
				<SearchField
					bind:value={filter}
					label="Filter the assembly tree"
					placeholder="Find a part, a screw or an assembly in the tree"
					noun="match"
					nouns="matches"
					found={filtering ? matchCount : null}
					wide
					class="min-w-0 flex-1"
				/>
				<DropdownMenu label="Filter and order the tree" menuClass="w-52">
					{#snippet trigger({ toggle, open })}
						{@const active = fGolden || fStable || order !== 'authored'}
						<span class="flex shrink-0">
							<button
								type="button"
								class="flex h-8 w-8 items-center justify-center border bg-surface {active
									? 'border-primary text-primary'
									: 'border-border text-text-muted'} hover:border-primary hover:text-primary"
								onclick={toggle}
								aria-expanded={open}
								title="Filter and order"
							>
								<SlidersHorizontal size={14} />
							</button>
							{#if active}
								<button
									type="button"
									class="-ml-px flex h-8 w-6 items-center justify-center border border-primary bg-surface text-primary hover:bg-primary/[0.06]"
									onclick={() => {
										fGolden = false;
										fStable = false;
										order = 'authored';
									}}
									title="Clear filter and order"
									aria-label="Clear filter and order"
								>
									<X size={12} />
								</button>
							{/if}
						</span>
					{/snippet}
					{#snippet children({ close })}
						{@const active = fGolden || fStable || order !== 'authored'}
						<div class="px-2.5 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-text-muted">Filter</div>
						<button
							type="button"
							class="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs text-text hover:bg-[var(--color-bg)]"
							onclick={() => (fGolden = !fGolden)}
						>
							<span>Golden</span>
							{#if fGolden}<Check size={12} class="ml-auto text-primary" />{/if}
						</button>
						<button
							type="button"
							class="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs text-text hover:bg-[var(--color-bg)]"
							onclick={() => (fStable = !fStable)}
						>
							<span>Stable</span>
							{#if fStable}<Check size={12} class="ml-auto text-primary" />{/if}
						</button>
						<div class="px-2.5 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-text-muted">Order</div>
						{#each [['authored', 'As authored'], ['name', 'By name']] as [o, lbl] (o)}
							<button
								type="button"
								class="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs text-text hover:bg-[var(--color-bg)]"
								onclick={() => (order = o as typeof order)}
							>
								<span>{lbl}</span>
								{#if order === o}<Check size={12} class="ml-auto text-primary" />{/if}
							</button>
						{/each}
						<div class="mt-1 border-t border-border">
							<button
								type="button"
								class="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs {active
									? 'text-text hover:bg-[var(--color-bg)]'
									: 'cursor-default text-text-muted/50'}"
								disabled={!active}
								onclick={() => {
									fGolden = false;
									fStable = false;
									order = 'authored';
									close();
								}}
							>
								<X size={12} />
								<span>Reset</span>
							</button>
						</div>
					{/snippet}
				</DropdownMenu>
				<button
					class="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-primary hover:text-primary-hover"
					onclick={downloadCsv}
					title="Exports the tree as configured here: {layers} layers, with every quantity multiplied down and STL links included."
				>
					<Download size={13} /> CSV
					<span class="font-normal text-text-muted">· {layers} layers</span>
				</button>
			</div>
			{#if filtering && matchCount === 0}
				<p class="px-1 py-6 text-center text-sm text-text-muted">
					Nothing in the tree matches. Most branches are still stubs — the part may be in the
					catalog without being placed here yet.
				</p>
			{/if}
			{#if timeView && viewKeys && !filtering}
				<div class="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 border border-warning/50 bg-warning/[0.08] px-2.5 py-1.5 text-xs text-warning-dark">
					<History size={11} class="shrink-0" />
					<span class="font-semibold">{timeView.label}</span>
					{#each [['change', 'the change'], ['vs-now', 'vs now'], ['tree', 'just the tree']] as [m, lbl] (m)}
						<button
							type="button"
							class={timeView.mode === m ? 'font-semibold underline underline-offset-2' : 'hover:underline'}
							onclick={() => (timeView = { ...timeView!, mode: m as TimeMode })}
						>
							{lbl}
						</button>
					{/each}
					<button type="button" class="ml-auto font-medium underline underline-offset-2" onclick={() => (timeView = null)}>back to now</button>
				</div>
				{@render timeNode('machine', null, 0, viewKeys.a, viewKeys.b)}
			{:else}
				{@render node('machine', 1, 1, 0)}
			{/if}
	</section>
</div>

<AssemblyDetailModal bind:open={asmOpen} id={asmId} {layers} onPart={openPart} onHardware={openHardware} />
<PartDetailModal bind:open={partOpen} part={partModal} bind:colorId={partColor} bind:version={partVersion} />
<HardwareDetailModal bind:open={hwOpen} hardware={hwModal} {layers} />

<style>
	/* Tree thumbnails open a detail view on click, so they carry the same click cue
	   as the parts/hardware lists: a primary-tinted ring on hover/focus. */
	.asm-thumb {
		display: block;
		cursor: pointer;
		transition: box-shadow 120ms ease;
	}
	.asm-thumb:hover,
	.asm-thumb:focus-visible {
		outline: none;
		box-shadow: 0 0 0 2px var(--color-primary);
	}
	/* The guide line under an open node is itself the collapse control: the
	   whole height is clickable. The visible line stays 1px (see CLAUDE.md
	   § Design rules) — hover recolors it instead of thickening it. */
	.tree-line {
		position: absolute;
		top: 2px;
		bottom: 0;
		left: 0;
		width: 14px;
		padding: 0;
		cursor: pointer;
	}
	.tree-line::before {
		content: '';
		position: absolute;
		top: 0;
		bottom: 0;
		left: 50%;
		width: 1px;
		margin-left: -0.5px;
		background: var(--color-border);
	}
	.tree-line:hover::before,
	.tree-line:focus-visible::before {
		background: var(--color-primary);
	}
</style>
