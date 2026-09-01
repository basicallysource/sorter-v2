<!--
	The line diagram for an assembly's connection edges: one brace per join
	method, drawn in the right gutter of the open node, spanning the rows of
	every member that method touches. The brace carries one word — the method —
	and clicking it opens a panel with the specifics (from → to, fastener and
	count, note, draft state). All-draft braces draw dashed.

	Renders as an absolutely-positioned overlay inside the node's branch
	container (its parent element), which reserves right padding for it. Rows
	are found by the data-member attribute the tree sets on each direct line
	row; positions re-measure on any size change of the branch.
-->
<script lang="ts">
	import type { Connection } from '$lib/filament';

	let {
		edges,
		labelOf,
		nameOf
	}: {
		edges: Connection[];
		labelOf: (method: string) => string;
		nameOf: (id: string) => string;
	} = $props();

	let host = $state<HTMLElement | null>(null);
	let open = $state<number | null>(null);

	const groups = $derived.by(() => {
		const m = new Map<string, Connection[]>();
		for (const e of edges) m.set(e.method, [...(m.get(e.method) ?? []), e]);
		return [...m.entries()].map(([method, es]) => ({
			method,
			edges: es,
			ids: [...new Set(es.flatMap((e) => [e.from, e.to, ...(e.via ? [e.via] : [])]))],
			draft: es.every((e) => e.draft)
		}));
	});

	let spans = $state<{ ys: number[] }[]>([]);
	function measure() {
		const parent = host?.parentElement;
		if (!parent) return;
		const pr = parent.getBoundingClientRect();
		spans = groups.map((g) => {
			const ys: number[] = [];
			for (const id of g.ids) {
				const el = parent.querySelector(`:scope > [data-member="${CSS.escape(id)}"]`);
				if (el) {
					const r = el.getBoundingClientRect();
					ys.push(r.top - pr.top + r.height / 2);
				}
			}
			return { ys: ys.sort((a, b) => a - b) };
		});
	}
	$effect(() => {
		void groups;
		measure();
		const parent = host?.parentElement;
		if (!parent) return;
		const ro = new ResizeObserver(measure);
		ro.observe(parent);
		return () => ro.disconnect();
	});
	function onWinClick(e: MouseEvent) {
		if (open !== null && !host?.contains(e.target as Node)) open = null;
	}
</script>

<svelte:window onclick={onWinClick} onkeydown={(e) => e.key === 'Escape' && (open = null)} />

<div bind:this={host} class="pointer-events-none absolute inset-y-0 right-0 w-0">
	{#each groups as g, i (g.method)}
		{@const s = spans[i]}
		{#if s && s.ys.length >= 1}
			{@const x = 14 + i * 12}
			{@const top = s.ys[0]}
			{@const bottom = s.ys[s.ys.length - 1]}
			<!-- the spine (1px, per the hairline rule; dashed when all-draft) -->
			<div
				class="absolute {g.draft ? 'border-l border-dashed border-warning' : 'bg-warning'}"
				style="right: {x}px; top: {top}px; height: {Math.max(1, bottom - top)}px; width: 1px;"
			></div>
			{#each s.ys as y (y)}
				<div class="absolute bg-warning" style="right: {x}px; top: {y}px; width: 9px; height: 1px;"></div>
			{/each}
			<button
				type="button"
				class="pointer-events-auto absolute z-10 -translate-y-1/2 border bg-surface px-1 py-px text-[10px] font-semibold uppercase tracking-wider {open === i
					? 'border-warning text-warning-dark'
					: 'border-warning/60 text-warning-dark hover:border-warning'}"
				style="right: {x - 5}px; top: {(top + bottom) / 2}px;"
				aria-expanded={open === i}
				onclick={() => (open = open === i ? null : i)}
			>
				{labelOf(g.method)}
			</button>
			{#if open === i}
				<div
					class="setup-panel pointer-events-auto absolute z-30 w-72 p-2.5 text-xs"
					style="right: {x + 8}px; top: {(top + bottom) / 2}px;"
				>
					{#each g.edges as e, j (j)}
						<div class="{j > 0 ? 'mt-1.5 border-t border-border/60 pt-1.5' : ''}">
							<div class="flex flex-wrap items-baseline gap-x-1.5">
								<span class="font-semibold text-text">{nameOf(e.from)}</span>
								<span class="text-text-muted">→</span>
								<span class="font-semibold text-text">{nameOf(e.to)}</span>
								{#if e.draft}
									<span
										class="border border-dashed border-warning/60 px-1 py-px text-[10px] font-semibold uppercase tracking-wider text-warning-dark"
										title="Extracted from prose — not yet confirmed at the bench">draft</span>
								{/if}
							</div>
							<div class="text-text-muted">
								{#if e.via}{e.qty} × {nameOf(e.via)}{:else}{labelOf(e.method)}{e.qty > 1 ? ` — ${e.qty} places` : ''}{/if}
							</div>
							{#if e.note}<div class="mt-0.5 text-text-muted">{e.note}</div>{/if}
						</div>
					{/each}
				</div>
			{/if}
		{/if}
	{/each}
</div>
