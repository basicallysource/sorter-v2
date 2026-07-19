<script lang="ts">
	import type { BrickLinkColor, PartBrickLinkColor } from '$lib/api';
	import { similarColors } from '$lib/colorLab';
	import Spinner from '$lib/components/Spinner.svelte';

	// What this mold actually exists in, ranked by pieces for sale. Every color is
	// shown — an earlier version filtered the list to solid colors near the guess
	// and so hid that 98347 is sold almost exclusively in Flat Silver and Pearl
	// Dark Gray. Never hide a color here: the whole point is to reveal the ones
	// you wouldn't have thought of.
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

	const guess = $derived(palette.find((c) => c.id === guessColorId) ?? null);
	// Marked, never filtered — a nudge toward the colors worth a second look.
	const similarIds = $derived(new Set(similarColors(palette, guess).map((c) => c.id)));
	const guessItem = $derived(items.find((it) => it.color_id === guessColorId) ?? null);

	const rows = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (!q) return items;
		return items.filter(
			(it) => it.color_name.toLowerCase().includes(q) || String(it.color_id) === q
		);
	});

	const maxQty = $derived(Math.max(1, ...items.map((it) => it.qty)));

	function fmtQty(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${Math.round(n / 1000)}k`;
		return String(n);
	}

	const asOf = $derived(updatedAt ? new Date(updatedAt).toLocaleDateString() : null);
</script>

<div class="flex flex-col border border-border bg-surface">
	<div class="border-b border-border px-3 py-2">
		<div class="text-sm font-medium text-text">Sold on BrickLink</div>
		<div class="text-xs text-text-muted">
			{#if !loading && items.length > 0}
				{items.length} color{items.length === 1 ? '' : 's'} for sale · {source === 'live'
					? 'live'
					: (asOf ?? 'cached')}
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
		<p class="p-4 text-sm text-text-muted">No BrickLink listings found for this part.</p>
	{:else}
		<!-- Called out explicitly: a guess that nobody stocks is strong evidence
		     against it, and that's invisible if the row just isn't in the list. -->
		{#if guess && !guessItem}
			<div class="border-b border-border bg-warning/[0.08] px-2 py-1.5 text-xs text-text-muted">
				<span
					class="mr-1 inline-block h-3 w-3 translate-y-0.5 border border-border"
					style={`background:#${guess.rgb ?? '000'}`}
				></span>
				No {guess.name} listed for sale
			</div>
		{/if}

		{#if items.length > 8}
			<div class="border-b border-border p-2">
				<input
					type="text"
					bind:value={search}
					placeholder="Search colors…"
					class="w-full border border-border bg-bg px-2 py-1 text-xs text-text placeholder:text-text-muted focus:border-primary focus:outline-none"
				/>
			</div>
		{/if}

		<div class="flex flex-col">
			{#each rows as it (it.color_id)}
				{@const isGuess = it.color_id === guessColorId}
				<div
					class="relative flex items-center gap-2 border-b border-border px-2 py-1.5 last:border-b-0 {isGuess
						? 'bg-info/[0.1]'
						: ''}"
					title={`${it.color_name} (${it.color_id}) · ${it.qty.toLocaleString()} pieces in ${it.lots.toLocaleString()} lots · ${it.qty_new.toLocaleString()} new / ${it.qty_used.toLocaleString()} used`}
				>
					<div
						class="pointer-events-none absolute inset-y-0 left-0 bg-primary-light"
						style={`width:${((it.qty / maxQty) * 100).toFixed(1)}%`}
					></div>
					<span
						class="relative h-4 w-4 shrink-0 border border-border {it.is_trans ? 'opacity-70' : ''}"
						style={`background:#${it.rgb ?? '000'}`}
					></span>
					<span
						class="relative min-w-0 flex-1 truncate text-xs {isGuess || similarIds.has(it.color_id)
							? 'font-medium text-text'
							: 'text-text-muted'}"
					>
						{it.color_name}{#if isGuess}<span class="ml-1 text-info">· guess</span>{/if}
					</span>
					<span class="relative shrink-0 text-xs tabular-nums text-text-muted">{fmtQty(it.qty)}</span>
				</div>
			{/each}
		</div>
		{#if rows.length === 0}
			<p class="p-3 text-xs text-text-muted">No colors match “{search}”.</p>
		{/if}
	{/if}
</div>
