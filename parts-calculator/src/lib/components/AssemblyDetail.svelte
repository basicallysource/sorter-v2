<script lang="ts">
	import { ArrowRight, BookOpen, Boxes, ExternalLink, FlaskConical, History, Zap } from 'lucide-svelte';
	import AlternativeBadge from '$lib/components/AlternativeBadge.svelte';
	import AssemblyDescription from '$lib/components/AssemblyDescription.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import ChangeStatus from '$lib/components/ChangeStatus.svelte';
	import ConflictBadge from '$lib/components/ConflictBadge.svelte';
	import HardwareIcon from '$lib/components/HardwareIcon.svelte';
	import ImageStrip from '$lib/components/ImageStrip.svelte';
	import {
		concreteLines,
		docsUrl,
		fmtDate,
		getAssembly,
		getHardware,
		getLasercut,
		getPart,
		hardwareImage,
		JOIN_LABELS,
		lineQty,
		type Assembly,
		type AssemblyLine,
		type Hardware,
		type Joining,
		type Part
	} from '$lib/filament';

	/**
	 * One assembly as a single object: what it is, what it looks like, and every
	 * line it is made of. The same view backs the rollup rows on the parts
	 * dashboard and the nodes of the assembly tree, so "open the PSU box" means
	 * the same thing wherever you click it.
	 *
	 * It renders exactly one level. A sub-assembly is a row you can open in turn
	 * rather than an inline tree — the tree page already shows the whole thing
	 * nested, and the point of this view is the opposite: one box at a time.
	 */
	let {
		assembly,
		layers,
		onPart,
		onHardware,
		onAssembly
	}: {
		assembly: Assembly;
		layers: number;
		onPart?: (p: Part) => void;
		onHardware?: (h: Hardware) => void;
		onAssembly?: (id: string) => void;
	} = $props();

	/** Printed parts reachable below an assembly, id -> count, quantities
	 *  multiplied down. Depth-capped rather than cycle-checked: authored data has
	 *  no cycles, and a `seen` set would undercount a part used in two branches. */
	function partsUnder(id: string, mult = 1, acc = new Map<string, number>(), depth = 0) {
		if (depth > 8) return acc;
		const asm = getAssembly(id);
		for (const line of concreteLines(asm ?? {}, asm?.lines ?? [])) {
			const q = lineQty(line, layers) * mult;
			if (line.assembly) partsUnder(line.assembly, q, acc, depth + 1);
			else if (line.part && getPart(line.part)) acc.set(line.part, (acc.get(line.part) ?? 0) + q);
		}
		return acc;
	}
	const grams = (counts: Map<string, number>) =>
		[...counts].reduce((g, [id, n]) => g + (getPart(id)?.grams ?? 0) * n, 0);

	// The header always shows something visual. An assembly's own pictures come
	// first when it has them; the members' renders stand in when it doesn't.
	const own = $derived(partsUnder(assembly.id));
	const fan = $derived([...own.keys()].map((id) => getPart(id)!).filter(Boolean).slice(0, 5));
	const totalGrams = $derived(grams(own));
	const totalPieces = $derived([...own.values()].reduce((n, q) => n + q, 0));

	const fmtG = (g: number) => (g >= 1000 ? `${(g / 1000).toFixed(2)} kg` : `${g.toFixed(0)} g`);
</script>

{#snippet joining(list: Joining[] | undefined)}
	{#each list ?? [] as j (j.method)}
		<div class="mt-1 flex flex-wrap items-baseline gap-x-2">
			<Badge variant="warning"><Zap size={10} />{JOIN_LABELS[j.method]}</Badge>
			{#if j.note}<AssemblyDescription text={j.note} as="span" class="text-xs text-text-muted" />{/if}
		</div>
	{/each}
{/snippet}

<!-- One BOM line. Which of the four kinds it is comes from where the id
     resolves, the same lookup order the tree uses. -->
{#snippet lineRow(line: AssemblyLine)}
	{@const each = lineQty(line, layers)}
	{#if line.assembly}
		{@const sub = getAssembly(line.assembly)}
		{#if sub}
			{@const counts = partsUnder(sub.id)}
			<button type="button" class="ad-row ad-row-open" onclick={() => onAssembly?.(sub.id)}>
				<span class="ad-fan">
					{#each [...counts.keys()].slice(0, 3) as pid, i (pid)}
						<span class="ad-thumb" style="z-index:{3 - i}"
							><img src={getPart(pid)?.render} alt="" /></span>
					{/each}
					{#if !counts.size}<span class="ad-thumb ad-thumb-empty"><Boxes size={16} /></span>{/if}
				</span>
				<span class="ad-body">
					<span class="ad-name">{sub.name} <Badge variant="info">Assembly</Badge></span>
					<span class="ad-meta"
						>{counts.size
							? `${counts.size} printed part${counts.size === 1 ? '' : 's'} · ${fmtG(grams(counts))}`
							: 'Nothing recorded inside yet'}</span>
				</span>
				<span class="ad-qty">×{each}</span>
				<ArrowRight size={14} class="ad-go" />
			</button>
		{/if}
	{:else if line.part && getLasercut(line.part)}
		{@const lc = getLasercut(line.part)!}
		<div class="ad-row">
			<span class="ad-fan"><span class="ad-thumb"><img src={lc.preview} alt="" /></span></span>
			<span class="ad-body">
				<span class="ad-name">{lc.name} <Badge variant="neutral">Laser cut</Badge></span>
				<span class="ad-meta">{lc.thicknessIn} plywood · {lc.widthMm}×{lc.heightMm} mm</span>
			</span>
			<span class="ad-qty">×{each}</span>
		</div>
	{:else if line.part && getHardware(line.part)}
		{@const hw = getHardware(line.part)!}
		{@const img = hardwareImage(hw)}
		<button type="button" class="ad-row ad-row-open" onclick={() => onHardware?.(hw)}>
			<span class="ad-fan">
				<span class="ad-thumb">
					{#if img}<img src={img.src} alt="" />{:else}<HardwareIcon {hw} size={18} />{/if}
				</span>
			</span>
			<span class="ad-body">
				<span class="ad-name">
					<HardwareIcon {hw} size={14} />{hw.name}
					<AlternativeBadge value={hw.alternative} size={14} />
					<ConflictBadge conflicts={hw.conflicts} size={14} />
				</span>
				<span class="ad-meta">Off the shelf</span>
			</span>
			<span class="ad-qty">×{each}</span>
			<ArrowRight size={14} class="ad-go" />
		</button>
	{:else if line.part && getPart(line.part)}
		{@const part = getPart(line.part)!}
		<button type="button" class="ad-row ad-row-open" onclick={() => onPart?.(part)}>
			<span class="ad-fan"><span class="ad-thumb"><img src={part.render} alt="" /></span></span>
			<span class="ad-body">
				<span class="ad-name">
					{part.name} <Badge variant="neutral">3D printed</Badge>
					<ChangeStatus kind="parts" id={part.id} name={part.name} />
				</span>
				<span class="ad-meta">{part.grams.toFixed(0)} g each · {part.uid}</span>
			</span>
			<span class="ad-qty">×{each}</span>
			<ArrowRight size={14} class="ad-go" />
		</button>
	{/if}
{/snippet}

<div class="ad">
	<header class="ad-head">
		{#if assembly.images?.length}
			<ImageStrip images={assembly.images} hero />
		{:else if fan.length}
			<div class="ad-fan ad-fan-lg">
				{#each fan as p, i (p.id)}
					<span class="ad-thumb ad-thumb-lg" style="z-index:{5 - i}"
						><img src={p.render} alt={p.name} /></span>
				{/each}
			</div>
		{/if}

		<div class="mt-2 flex flex-wrap items-center gap-2">
			<span class="font-mono text-xs text-text">{assembly.uid}</span>
			{#if assembly.version}<span class="text-xs text-text-muted">v{assembly.version}</span>{/if}
			<ChangeStatus kind="assemblies" id={assembly.id} name={assembly.name} />
		</div>

		{#if assembly.description}
			<AssemblyDescription text={assembly.description} class="mt-1.5 text-sm text-text-muted" />
		{/if}
		{@render joining(assembly.joining)}
		{#if docsUrl(assembly)}
			<a
				href={docsUrl(assembly)}
				target="_blank"
				rel="noopener"
				class="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-hover"
			>
				<BookOpen size={12} /> Assembly guide <ExternalLink size={10} />
			</a>
		{/if}
	</header>

	<section class="ad-sec">
		<h3 class="ad-hd">
			Contents
			{#if totalPieces}
				<span class="ad-hd-note"
					>{totalPieces} printed piece{totalPieces === 1 ? '' : 's'} · {fmtG(totalGrams)}</span>
			{/if}
		</h3>
		{#if assembly.lines?.length}
			<!-- param slots resolve to their defaults here: this view shows the
			     assembly itself, not one parent's instantiation of it -->
			{#each concreteLines(assembly, assembly.lines) as line, i (`${line.part ?? line.assembly}-${i}`)}
				{@render lineRow(line)}
			{/each}
		{:else}
			<p class="text-sm text-text-muted">
				Nothing has been recorded inside this assembly yet.
			</p>
		{/if}
	</section>

	<!-- Alternative bills of materials under test. Nothing here reaches any total:
	     the resolvers walk `lines` only. This is the one place the dashboard could
	     previously not show that a revision was on the table. -->
	{#each assembly.candidates ?? [] as c (c.uid)}
		{@const retired = !!(c.superseded_by || c.rejected_at)}
		<section class="ad-cand {retired ? 'ad-cand-retired' : ''}">
			<div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
				<span
					class="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-primary"
					><FlaskConical size={11} /> Candidate</span>
				{#if c.name}<span class="text-sm font-semibold text-text">{c.name}</span>{/if}
				<span class="font-mono text-xs text-text">{c.uid}</span>
				<span class="text-xs text-text-muted">· {fmtDate(c.created_at)}</span>
				{#if retired}
					<span
						class="border border-border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-text-muted"
						>{c.rejected_at ? 'rejected' : 'superseded'}</span>
				{/if}
			</div>
			<AssemblyDescription text={c.message} class="mt-0.5 text-xs text-text-muted" />
			{#if c.images?.length}<div class="mt-2"><ImageStrip images={c.images} /></div>{/if}
			{@render joining(c.joining)}
			<p class="mt-1 text-xs italic text-text-muted/70">
				An alternative bill of materials under test — not part of the build and not in the totals.
			</p>
			{#each c.lines as line, i (`${line.part ?? line.assembly}-${i}`)}
				{@render lineRow(line)}
			{/each}
		</section>
	{/each}

	{#if (assembly.versions?.length ?? 0) > 1}
		<details class="ad-sec">
			<summary
				class="inline-flex cursor-pointer items-center gap-1 text-xs font-semibold uppercase tracking-wider text-text-muted hover:text-text"
				><History size={11} /> Previous revisions · {(assembly.versions?.length ?? 1) - 1}</summary>
			{#each [...(assembly.versions ?? [])].slice(0, -1).reverse() as v (v.version)}
				<div class="mt-2 border border-border bg-surface p-2 text-xs sm:p-3">
					<div class="flex flex-wrap items-baseline gap-x-2">
						<b class="text-text">v{v.version}</b>
						{#if v.uid}<span class="font-mono text-text-muted">{v.uid}</span>{/if}
						<span class="text-text-muted">· {fmtDate(v.date)}</span>
					</div>
					<AssemblyDescription text={v.message} class="mt-0.5 text-text-muted" />
					{#if v.images?.length}<div class="mt-2"><ImageStrip images={v.images} /></div>{/if}
					<ul class="mt-1.5 space-y-0.5 text-text-muted">
						{#each v.lines ?? [] as l, i (`${l.part ?? l.assembly}-${i}`)}
							{@const name =
								(l.part &&
									(getPart(l.part)?.name ??
										getHardware(l.part)?.name ??
										getLasercut(l.part)?.name)) ??
								(l.assembly && getAssembly(l.assembly)?.name) ??
								l.part ??
								l.assembly}
							<li>
								<span class="tabular-nums">×{l.qty}</span>
								{name}{#if l.uid}<span class="ml-1 font-mono">{l.uid}</span>{/if}
							</li>
						{/each}
					</ul>
				</div>
			{/each}
		</details>
	{/if}
</div>

<style>
	.ad {
		padding: 0.75rem 1rem 1rem;
	}
	.ad-head {
		padding-bottom: 0.75rem;
		border-bottom: 1px solid var(--color-border);
	}
	.ad-sec {
		margin-top: 1rem;
	}
	.ad-hd {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0.5rem;
		margin-bottom: 0.375rem;
		font-size: 0.6875rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-text-muted);
	}
	.ad-hd-note {
		text-transform: none;
		letter-spacing: 0;
		font-weight: 400;
		font-size: 0.75rem;
		font-variant-numeric: tabular-nums;
	}

	/* One line of the bill. A row that opens something carries the arrow and the
	   hover ring; a laser-cut line, which has no detail view yet, does not. */
	.ad-row {
		display: flex;
		width: 100%;
		align-items: center;
		gap: 0.75rem;
		padding: 0.5rem;
		border: 1px solid var(--color-border);
		background: var(--color-surface);
		text-align: left;
	}
	.ad-row + .ad-row {
		margin-top: -1px;
	}
	.ad-row-open {
		cursor: pointer;
		transition:
			border-color 120ms ease,
			background-color 120ms ease;
	}
	.ad-row-open:hover,
	.ad-row-open:focus-visible {
		outline: none;
		position: relative;
		z-index: 1;
		border-color: var(--color-primary);
		background: color-mix(in oklab, var(--color-primary) 5%, var(--color-surface));
	}
	.ad-body {
		display: flex;
		min-width: 0;
		flex: 1;
		flex-direction: column;
	}
	.ad-name {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.375rem;
		font-size: 0.875rem;
		font-weight: 600;
		color: var(--color-text);
	}
	.ad-meta {
		margin-top: 0.125rem;
		font-size: 0.75rem;
		color: var(--color-text-muted);
	}
	.ad-qty {
		font-size: 0.8125rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--color-text);
	}
	:global(.ad-go) {
		flex: none;
		color: var(--color-text-muted);
	}
	.ad-row-open:hover :global(.ad-go) {
		color: var(--color-primary);
	}

	.ad-fan {
		display: flex;
		flex: none;
	}
	.ad-thumb {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 2.25rem;
		height: 2.25rem;
		flex: none;
		border: 1px solid var(--color-border);
		background: var(--color-bg);
		padding: 0.125rem;
	}
	.ad-thumb img {
		width: 100%;
		height: 100%;
		object-fit: contain;
	}
	.ad-thumb + .ad-thumb {
		margin-left: -0.625rem;
	}
	.ad-thumb-empty {
		color: var(--color-text-muted);
	}
	.ad-fan-lg .ad-thumb-lg {
		width: 3.5rem;
		height: 3.5rem;
	}
	.ad-fan-lg .ad-thumb-lg + .ad-thumb-lg {
		margin-left: -0.875rem;
	}

	.ad-cand {
		margin-top: 1rem;
		padding: 0.625rem;
		border: 1px dashed color-mix(in oklab, var(--color-primary) 60%, transparent);
	}
	.ad-cand-retired {
		border-color: var(--color-border);
		opacity: 0.6;
	}
	.ad-cand .ad-row:first-of-type {
		margin-top: 0.5rem;
	}
</style>
