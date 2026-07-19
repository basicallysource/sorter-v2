<script lang="ts">
	import type { BrickLinkColor, PartBrickLinkColor } from '$lib/api';
	import { similarColors } from '$lib/colorLab';
	import Spinner from '$lib/components/Spinner.svelte';

	// Marketplace prior for the labeler. A global top-20 is useless here — it just
	// says "lots of white ones exist". What decides a call is: among the colors
	// this piece could plausibly BE, which does BrickLink actually stock? So the
	// default view is the predicted color plus its Lab neighbours, ranked by
	// pieces for sale. Data is the cached price guide in parts.db.
	let {
		palette,
		items,
		guessColorId,
		partName,
		itemNo,
		updatedAt,
		source = 'cache',
		loading = false,
		error = null
	}: {
		palette: BrickLinkColor[];
		items: PartBrickLinkColor[];
		guessColorId: number | null;
		partName?: string | null;
		itemNo?: string | null;
		updatedAt?: string | null;
		source?: 'live' | 'cache';
		loading?: boolean;
		error?: string | null;
	} = $props();

	let search = $state('');
	let showAll = $state(false);

	const qtyById = $derived(new Map(items.map((it) => [it.color_id, it])));
	const guess = $derived(palette.find((c) => c.id === guessColorId) ?? null);

	type Row = { color: BrickLinkColor; qty: number; isGuess: boolean };

	function toRow(color: BrickLinkColor): Row {
		return { color, qty: qtyById.get(color.id)?.qty ?? 0, isGuess: color.id === guessColorId };
	}

	// Neighbours of the guess, ranked by availability — the actual decision aid.
	// Colors with nothing for sale sink to the bottom but stay visible: "nobody
	// sells this mold in umber" is itself a useful answer.
	const similar = $derived(
		similarColors(palette, guess)
			.map(toRow)
			.sort((a, b) => b.qty - a.qty)
	);

	// Everything BrickLink stocks for this part, most pieces first (items already
	// arrives sorted). Reachable via search or the "all colors" toggle.
	const all = $derived(
		items.map((it) => {
			const color = palette.find((c) => c.id === it.color_id);
			return {
				color: color ?? {
					id: it.color_id,
					name: it.color_name,
					rgb: it.rgb,
					is_trans: it.is_trans
				},
				qty: it.qty,
				isGuess: it.color_id === guessColorId
			} satisfies Row;
		})
	);

	const rows = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (q) {
			return all.filter((r) => r.color.name.toLowerCase().includes(q) || String(r.color.id) === q);
		}
		return showAll ? all : similar;
	});

	const guessRow = $derived(guess && !search.trim() && !showAll ? toRow(guess) : null);
	const maxQty = $derived(Math.max(1, ...rows.map((r) => r.qty), guessRow?.qty ?? 0));

	function fmtQty(n: number): string {
		if (n <= 0) return '—';
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${Math.round(n / 1000)}k`;
		return String(n);
	}

	const asOf = $derived(updatedAt ? new Date(updatedAt).toLocaleDateString() : null);
</script>

{#snippet row(r: Row)}
	<div
		class="relative flex items-center gap-2 border-b border-border px-2 py-1.5 last:border-b-0 {r.isGuess
			? 'bg-info/[0.08]'
			: ''}"
		title={`${r.color.name} (${r.color.id}) · ${r.qty > 0 ? `${r.qty.toLocaleString()} pieces for sale` : 'none listed for sale'}`}
	>
		<!-- Bar is relative to the most-stocked row in view, so a shortlist of rare
		     colors still shows its own spread instead of flatlining. -->
		<div
			class="pointer-events-none absolute inset-y-0 left-0 bg-primary-light"
			style={`width:${((r.qty / maxQty) * 100).toFixed(1)}%`}
		></div>
		<span
			class="relative h-4 w-4 shrink-0 border border-border {r.color.is_trans ? 'opacity-70' : ''}"
			style={`background:#${r.color.rgb ?? '000'}`}
		></span>
		<span
			class="relative min-w-0 flex-1 truncate text-xs {r.isGuess
				? 'font-medium text-text'
				: 'text-text-muted'}"
		>
			{r.color.name}{#if r.isGuess}<span class="ml-1 text-info">· guess</span>{/if}
		</span>
		<span class="relative shrink-0 text-xs tabular-nums text-text-muted">{fmtQty(r.qty)}</span>
	</div>
{/snippet}

<div class="flex flex-col border border-border bg-surface">
	<div class="border-b border-border px-3 py-2">
		<div class="text-sm font-medium text-text">Sold on BrickLink</div>
		<div class="text-xs text-text-muted">
			{#if !loading && (items.length > 0 || similar.length > 0)}
				{partName || itemNo} · pieces for sale · {source === 'live' ? 'live' : (asOf ?? 'cached')}
			{:else}
				what colors this part comes in
			{/if}
		</div>
	</div>

	{#if loading}
		<div class="flex justify-center py-8"><Spinner /></div>
	{:else if error}
		<div class="p-3 text-sm text-primary">{error}</div>
	{:else if items.length === 0}
		<p class="p-4 text-sm text-text-muted">No BrickLink listings cached for this part.</p>
	{:else}
		<div class="flex items-center gap-1 border-b border-border p-2">
			<input
				type="text"
				bind:value={search}
				placeholder="Search colors…"
				class="min-w-0 flex-1 border border-border bg-bg px-2 py-1 text-xs text-text placeholder:text-text-muted focus:border-primary focus:outline-none"
			/>
			{#if !search.trim() && guess}
				<button
					class="shrink-0 border border-border px-2 py-1 text-xs text-text-muted hover:border-primary"
					onclick={() => (showAll = !showAll)}
				>
					{showAll ? 'Near guess' : 'All'}
				</button>
			{/if}
		</div>

		{#if guessRow}
			{@render row(guessRow)}
		{/if}
		{#if rows.length === 0}
			<p class="p-3 text-xs text-text-muted">
				{search.trim() ? `No colors match “${search}”.` : 'No similar colors to compare.'}
			</p>
		{:else}
			<div class="flex flex-col">
				{#each rows as r (r.color.id)}
					{@render row(r)}
				{/each}
			</div>
		{/if}
	{/if}
</div>
