<script lang="ts">
	import { BookOpen, Download, ExternalLink, FlaskConical, History, ShoppingCart, Zap } from 'lucide-svelte';
	import AlternativeBadge from '$lib/components/AlternativeBadge.svelte';
	import ConflictBadge from '$lib/components/ConflictBadge.svelte';
	import AssemblyDescription from '$lib/components/AssemblyDescription.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import LayerControl from '$lib/components/LayerControl.svelte';
	import PartDetailModal from '$lib/components/PartDetailModal.svelte';
	import AssemblyDetailModal from '$lib/components/AssemblyDetailModal.svelte';
	import HardwareDetailModal from '$lib/components/HardwareDetailModal.svelte';
	import HardwareIcon from '$lib/components/HardwareIcon.svelte';
	import ImageStrip from '$lib/components/ImageStrip.svelte';
	import Seo from '$lib/components/Seo.svelte';
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
		primaryColorId,
		resolveHardwareTotals,
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

	// ?focus=<assembly id> — the hardware page links here to answer "where does
	// this screw actually go?". Read in an effect rather than derived: the site is
	// prerendered, so query params don't exist until the page is in a browser.
	let focus = $state<string | null>(null);
	$effect(() => {
		const target = page.url.searchParams.get('focus');
		focus = target;
		if (!target) return;
		// Part renders load after first paint and shift everything down, so one
		// scroll lands short. Re-aim a few times while the layout settles.
		const aim = () => document.getElementById(`asm-${target}`)?.scrollIntoView({ block: 'center' });
		const timers = [0, 120, 400, 900].map((t) => setTimeout(aim, t));
		return () => timers.forEach(clearTimeout);
	});

	// What the badges mean. The tree records that a node is incomplete but not
	// which pieces are missing, so the tooltip says exactly that much and no more.
	const STATUS_NOTE = {
		stub: 'Placeholder — nothing has been recorded inside this assembly yet. What it actually contains is not captured anywhere in the data.',
		partial: 'Some of this assembly is recorded, but not all of it. The parts and hardware shown are real; the list is known to be missing pieces, and the data does not say which.'
	};

	type HardwareTotal = { hw: Hardware; qty: number };
	const hardwareTotals: HardwareTotal[] = $derived.by(() =>
		[...resolveHardwareTotals('machine', layers).entries()]
			.map(([id, qty]) => ({ hw: getHardware(id)!, qty }))
			.filter((t) => t.hw)
	);

	const fmtUsd = (n: number) => `$${n.toFixed(2)}`;

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

<Seo
	title="Machine assembly"
	description="The Sorter V2 machine as a recursive assembly tree — printed parts, sub-assemblies and hardware, layer by layer."
/>

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
		{#if line.assembly}
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
	{#if asm}
		<div
			id="asm-{asm.id}"
			class="border-l-2 {depth > 0 ? 'ml-1.5 pl-2 sm:ml-4 sm:pl-4' : 'pl-2 sm:pl-4'} py-2 {focus === asm.id
				? 'border-primary bg-primary/[0.06]'
				: 'border-border'}"
		>
			<div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
				<button type="button" class="asm-open text-sm font-semibold text-text" onclick={() => openAssembly(asm.id)} title="View {asm.name} on its own">{asm.name}</button>
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
			</div>
			{#if asm.description}
				<AssemblyDescription
					text={asm.description}
					class="mt-0.5 max-w-2xl text-xs text-text-muted"
				/>
			{/if}
			{#if asm.images?.length}<div class="mt-2"><ImageStrip images={asm.images} /></div>{/if}
			<!-- The docs site is where the step-by-step build lives; this node is only
			     the bill of materials for it. Link out when a page exists. -->
			{#if docsUrl(asm)}
				<a
					href={docsUrl(asm)}
					target="_blank"
					rel="noopener"
					class="mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-hover"
				>
					<BookOpen size={11} /> Assembly guide <ExternalLink size={10} />
				</a>
			{/if}
			{@render joiningRows(asm.joining)}
			{@render lines(asm.lines ?? [], mult, depth)}
			<!-- Alternative bills of materials under test. Rendered with the same line
			     rows, but nothing here reaches the totals: resolveHardwareTotals walks
			     only `lines`. -->
			{#each asm.candidates ?? [] as c (c.uid)}
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
			{#if (asm.versions?.length ?? 0) > 1}
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
{/snippet}

<div class="mx-auto max-w-6xl px-4 py-8 sm:px-6">
	<header class="mb-5">
		<h1 class="text-2xl font-bold text-text">Machine assembly</h1>
		<p class="mt-1 max-w-3xl text-sm text-text-muted">
			The whole machine as one assembly tree — printed parts, and the hardware that goes into
			them, resolved from a single registry. Pick a subtree, get everything it needs.
		</p>
	</header>

	<div class="mb-5">
		<Callout variant="info" title="Experimental">
			This tab is the first cut of the unified parts system. Most branches are stubs; the chute
			core is the first part carrying real off-the-shelf hardware. The existing tabs stay
			authoritative until this fills in.
		</Callout>
	</div>

	<div class="mb-6"><LayerControl /></div>

	<div class="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
		<section class="setup-card-shell min-w-0 border p-2 sm:p-4">
			<div class="mb-3 flex items-center justify-between gap-3">
				<h2 class="text-xs font-semibold uppercase tracking-wider text-text-muted">
					Assembly tree
				</h2>
				<button
					class="inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-hover"
					onclick={downloadCsv}
					title="Exports the tree as configured here: {layers} layers, with every quantity multiplied down and STL links included."
				>
					<Download size={13} /> CSV
					<span class="font-normal text-text-muted">· {layers} layers</span>
				</button>
			</div>
			{@render node('machine', 1, 1, 0)}
		</section>

		<aside class="setup-card-shell min-w-0 border p-3 sm:p-4">
			<h2 class="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text-muted">
				<ShoppingCart size={13} /> Hardware to buy
			</h2>
			{#if hardwareTotals.length === 0}
				<p class="text-sm text-text-muted">Nothing yet.</p>
			{/if}
			{#each hardwareTotals as t (t.hw.id)}
				{@const img = hardwareImage(t.hw)}
				<div class="border border-border bg-[var(--color-bg)] p-3">
					<div class="flex items-start gap-3">
						{#if img}
							<button type="button" class="asm-thumb shrink-0" title="View {t.hw.name} details" onclick={() => openHardware(t.hw)}>
								<img src={img.src} alt={t.hw.name} class="h-14 w-14 object-contain" />
							</button>
						{/if}
						<div class="min-w-0">
							<div class="flex items-center gap-1.5 text-sm font-semibold text-text">
								<HardwareIcon hw={t.hw} size={16} /><span class="truncate">{t.hw.name}</span>
								<AlternativeBadge value={t.hw.alternative} size={16} />
								<ConflictBadge conflicts={t.hw.conflicts} size={16} />
							</div>
							<p class="mt-0.5 text-xs text-text-muted">{t.hw.description}</p>
						</div>
					</div>
					{#if t.hw.attributes.length}
						<dl class="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs text-text-muted">
							{#each t.hw.attributes as a}
								<dt>{a.label}</dt>
								<dd class="text-text">{a.value}</dd>
							{/each}
						</dl>
					{/if}
					<div class="mt-3 border-t border-border pt-2 text-sm text-text">
						<span class="font-semibold tabular-nums">{t.qty}</span> needed
						<span class="text-xs text-text-muted">across every branch below</span>
					</div>
					{#each (t.hw.sourcing?.vendors ?? []).filter((v) => v.price != null && v.pack_qty) as v (v.url)}
						{@const packs = Math.ceil(t.qty / v.pack_qty!)}
						<div class="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs">
							<a
								href={v.url}
								target="_blank"
								rel="noopener"
								class="inline-flex items-center gap-1 font-medium text-primary hover:text-primary-hover"
							>
								{v.vendor ?? v.region} <ExternalLink size={11} />
							</a>
							<span class="tabular-nums text-text-muted">
								{packs} × {v.pack_qty}-pack = <span class="font-semibold text-text">{fmtUsd(packs * v.price!)}</span>
								{#if v.note}<span> · {v.note}</span>{/if}
							</span>
						</div>
					{/each}
					{#if t.hw.sourcing?.vendors?.length && t.hw.sourcing.vendors[0].as_of}
						<p class="mt-1.5 text-[10px] text-text-muted">
							Prices as of {t.hw.sourcing.vendors[0].as_of}. Counts cover only the branches that
							have been filled in — the tree is still mostly partial.
						</p>
					{/if}
				</div>
			{/each}
		</aside>
	</div>
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
	/* The node's name opens the assembly on its own. Underlined on hover rather
	   than always, so a tree of two hundred names doesn't read as a link farm. */
	.asm-open {
		cursor: pointer;
		text-align: left;
		text-underline-offset: 3px;
	}
	.asm-open:hover,
	.asm-open:focus-visible {
		outline: none;
		color: var(--color-primary);
		text-decoration: underline;
	}
</style>
