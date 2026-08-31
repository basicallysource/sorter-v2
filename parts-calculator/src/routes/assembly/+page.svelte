<script lang="ts">
	import {
		BookOpen,
		ChevronDown,
		ChevronRight,
		Download,
		EllipsisVertical,
		ExternalLink,
		FlaskConical,
		History,
		Maximize2,
		Zap
	} from 'lucide-svelte';
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
		docsUrl,
		fmtDate,
		getAssembly,
		getHardware,
		getLasercut,
		getPart,
		hardwareImage,
		JOIN_LABELS,
		lineQty,
		plainDescription,
		primaryColorId,
		type AssemblyLine,
		type Hardware,
		type Joining,
		type Part,
		type PartVersion
	} from '$lib/filament';
	import { layerStore } from '$lib/layers.svelte';
	import { page } from '$app/state';
	import { assemblyCsv } from '$lib/parts-csv';
	import { download, exportSpec, filename } from '$lib/csv';

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
	// walking upward from a focus target.
	const parentOf = new Map<string, string>();
	{
		const walk = (id: string) => {
			for (const line of getAssembly(id)?.lines ?? []) {
				if (line.assembly && !parentOf.has(line.assembly)) {
					parentOf.set(line.assembly, id);
					walk(line.assembly);
				}
			}
		};
		walk('machine');
	}

	// ?focus=<assembly id> — the hardware page links here to answer "where does
	// this screw actually go?". Read in an effect rather than derived: the site is
	// prerendered, so query params don't exist until the page is in a browser.
	let focus = $state<string | null>(null);
	$effect(() => {
		const target = page.url.searchParams.get('focus');
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

	// ---- filtering the tree --------------------------------------------------
	// A tree can't be filtered like a list: hiding everything that doesn't match
	// would also hide the branch that tells you WHERE the match is, which is the
	// only reason to search a tree in the first place. So a node survives when it
	// matches or when anything beneath it does, and the path down to a match stays
	// on screen. An assembly that matches by its own name keeps its whole subtree
	// — you asked for the chute core, you want what is in it.
	let filter = $state('');
	const filtering = $derived(filter.trim().length > 0);

	/** Does this member — printed part, bought part or laser-cut sheet — match? */
	function memberMatches(id: string): boolean {
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
			let hit = !!scoreEntry(filter, {
				name: asm.name,
				uid: asm.uid,
				id: asm.id,
				text: plainDescription(asm.description)
			});
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

	// What the badges mean. The tree records that a node is incomplete but not
	// which pieces are missing, so the tooltip says exactly that much and no more.
	const STATUS_NOTE = {
		stub: 'Placeholder — nothing has been recorded inside this assembly yet. What it actually contains is not captured anywhere in the data.',
		partial: 'Some of this assembly is recorded, but not all of it. The parts and hardware shown are real; the list is known to be missing pieces, and the data does not say which.'
	};

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
	<div class="ml-1.5 mt-2 flex items-center gap-3 border border-border bg-[var(--color-bg)] p-2 sm:ml-4">
		{#if img}
			<button type="button" class="asm-thumb shrink-0" title="View {hw.name} details" onclick={() => openHardware(hw)}>
				<img src={img.src} alt={hw.name} class="h-8 w-8 object-contain" />
			</button>
		{/if}
		<div class="flex min-w-0 flex-1 items-center gap-1.5 text-xs font-semibold text-text">
			<HardwareIcon {hw} size={14} /><span class="truncate">{hw.name}</span>
			<AlternativeBadge value={hw.alternative} size={14} />
						<ConflictBadge conflicts={hw.conflicts} size={14} />
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

{#snippet lines(list: AssemblyLine[], mult: number, depth: number)}
	<!-- Keyed by position as well as id: two lines can legitimately name the
	     same part, and a bare id key makes that a duplicate-key error that
	     blanks the whole page on hydration. -->
	{#each list as line, i (`${line.part ?? line.assembly}-${i}`)}
		{#if !lineShown(line)}
			<!-- filtered out -->
		{:else if line.assembly}
			{@render node(line.assembly, line.qty, lineQty(line, layers) * mult, depth + 1)}
		{:else if line.part && getLasercut(line.part)}
			{@const lc = getLasercut(line.part)!}
			<div class="ml-1.5 mt-2 flex items-center gap-3 border border-border bg-surface p-2 sm:ml-4 sm:p-3">
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
				<div class="ml-1.5 mt-2 border border-border bg-surface p-2 sm:ml-4 sm:p-3">
					<div class="flex items-center gap-3">
						<button type="button" class="asm-thumb shrink-0" title="View {part.name} details" onclick={() => openPart(part)}>
							<img src={part.render} alt={part.name} class="h-12 w-12 object-contain" />
						</button>
						<div class="min-w-0 flex-1">
							<div class="flex flex-wrap items-baseline gap-x-2">
								<span class="text-sm font-semibold text-text">{part.name}</span>
								<span class="border border-border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-text-muted"
									>3D printed</span>
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

{#snippet node(id: string, qty: AssemblyLine['qty'], mult: number, depth: number)}
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
			class="{depth > 0 ? 'ml-1.5 mt-2 sm:ml-4' : ''} py-1 {focus === asm.id ? 'bg-primary/[0.06]' : ''}"
		>
			<div class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
				{#if hasContent}
					<button
						type="button"
						class="-ml-1 flex h-5 w-5 shrink-0 items-center justify-center text-text-muted hover:text-text"
						onclick={() => toggle(asm.id)}
						aria-expanded={open}
						aria-label="{open ? 'Collapse' : 'Expand'} {asm.name}"
					>
						{#if open}<ChevronDown size={14} />{:else}<ChevronRight size={14} />{/if}
					</button>
				{:else}
					<span class="-ml-1 h-5 w-5 shrink-0"></span>
				{/if}
				<button type="button" class="asm-open text-sm font-semibold text-text" onclick={() => openAssembly(asm.id)} title="View {asm.name} on its own">
					{asm.name}<span class="open-cue" aria-hidden="true"><Maximize2 size={11} /></span>
				</button>
				<span class="text-xs tabular-nums text-text-muted">
					{#if qty === 'per-layer'}×{layers} (1 per layer)
					{:else if qty === 'middle-layers'}×{Math.max(0, layers - 2)} (layers between the interfaces)
					{:else if qty !== 1}×{qty}{/if}
				</span>
				{#if asm.status === 'stub'}
					<span
						class="cursor-help border border-border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-text-muted"
						title={STATUS_NOTE.stub}>stub — not yet detailed</span>
				{:else if asm.status === 'partial'}
					<span
						class="cursor-help border border-warning/50 bg-warning/[0.08] px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-warning-dark"
						title={STATUS_NOTE.partial}>partial</span>
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
							<BookOpen size={11} /> Assembly guide <ExternalLink size={10} />
						</a>
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
							</div>
						{/if}
					{/if}
				</span>
			</div>
			<!-- The description is NOT rendered here on purpose: it lives in the
			     detail view a node's name opens. Inline it turns the tree into a
			     wall of prose that restates the line rows below it. -->
			{#if open}
			<div class="tree-branch relative pl-2 sm:pl-4">
				<button type="button" class="tree-line" onclick={() => toggle(asm.id)} aria-label="Collapse {asm.name}"></button>
			{#if asm.images?.length}<div class="mt-2"><ImageStrip images={asm.images} /></div>{/if}
			{@render joiningRows(asm.joining)}
			{@render lines(asm.lines ?? [], mult, depth)}
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
			<!-- Superseded structures, each line pinned to the member's uid of the day. -->
			{#if !filtering && (asm.versions?.length ?? 0) > 1}
				<details class="ml-1.5 mt-3 sm:ml-4">
					<summary class="inline-flex cursor-pointer items-center gap-1 text-xs font-semibold uppercase tracking-wider text-text-muted hover:text-text"><History size={11} /> Previous revisions · {(asm.versions?.length ?? 1) - 1}</summary>
					{#each [...(asm.versions ?? [])].slice(0, -1).reverse() as v (v.version)}
						<div class="mt-2 border border-border bg-surface p-2 text-xs sm:p-3">
							<div class="flex flex-wrap items-baseline gap-x-2">
								<b class="text-text">v{v.version}</b>
								{#if v.uid}<span class="font-mono text-text-muted">{v.uid}</span>{/if}
								<span class="text-text-muted">· {fmtDate(v.date)}</span>
							</div>
							<AssemblyDescription text={v.message} class="mt-0.5 max-w-2xl text-text-muted" />
							{#if v.images?.length}<div class="mt-2"><ImageStrip images={v.images} /></div>{/if}
							<ul class="mt-1.5 space-y-0.5 text-text-muted">
								{#each v.lines ?? [] as l, i (`${l.part ?? l.assembly}-${i}`)}
									{@const name = (l.part && (getPart(l.part)?.name ?? getHardware(l.part)?.name ?? getLasercut(l.part)?.name)) ?? (l.assembly && getAssembly(l.assembly)?.name) ?? l.part ?? l.assembly}
									<li><span class="tabular-nums">×{l.qty}</span> {name}{#if l.uid} <span class="font-mono">{l.uid}</span>{/if}</li>
								{/each}
							</ul>
						</div>
					{/each}
				</details>
			{/if}
			</div>
			{/if}
		</div>
	{/if}
{/snippet}

<div class="mx-auto max-w-6xl px-4 py-8 sm:px-6">
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
			{@render node('machine', 1, 1, 0)}
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
	/* The node's name opens the assembly's detail view — a modal, not a page,
	   so it must not read as a link: no blue, no underline. The cue is a small
	   expand glyph that fades in on hover, same idea as the thumbnail ring. */
	.asm-open {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		cursor: pointer;
		text-align: left;
	}
	.asm-open .open-cue {
		display: inline-flex;
		color: var(--color-text-muted);
		opacity: 0;
		transition: opacity 120ms ease;
	}
	.asm-open:hover .open-cue,
	.asm-open:focus-visible .open-cue {
		opacity: 1;
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
