<script lang="ts">
	import type { BrickLinkColor, PartBrickLinkColor } from '$lib/api';
	import { similarColors } from '$lib/colorLab';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Input from '$lib/components/Input.svelte';
	import Panel from '$lib/components/Panel.svelte';

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

<Panel
	title="Sold on BrickLink"
	description={!loading && items.length > 0
		? `${items.length} color${items.length === 1 ? '' : 's'} for sale, ${source === 'live' ? 'live' : (asOf ?? 'cached')}`
		: 'The colors this part comes in'}
	flush
>
	{#if loading}
		<div class="flex justify-center py-8"><Spinner size={32} /></div>
	{:else if error}
		<div class="px-(--pad-panel) pb-(--pad-panel)"><Alert tone="danger">{error}</Alert></div>
	{:else if items.length === 0}
		<p class="px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">No BrickLink listings for this part.</p>
	{:else}
		<!-- Said outright: a guess that nobody sells is strong evidence against it,
		     and a row that is simply missing would hide that. -->
		{#if guess && !guessItem}
			<div class="px-(--pad-panel) pb-3"><Alert tone="warning">No {guess.name} is for sale.</Alert></div>
		{/if}
		{#if items.length > 8}
			<div class="px-(--pad-panel) pb-3"><Input type="search" size="sm" bind:value={search} placeholder="Search the colors" /></div>
		{/if}
		<ul class="divide-y divide-line border-t border-line">
			{#each rows as it (it.color_id)}
				{@const isGuess = it.color_id === guessColorId}
				<li
					class="relative flex items-center gap-2 px-(--pad-panel) py-1.5 {isGuess ? 'bg-info-soft' : ''}"
					title={`${it.color_name} (${it.color_id}): ${it.qty.toLocaleString()} pieces in ${it.lots.toLocaleString()} lots, ${it.qty_new.toLocaleString()} new and ${it.qty_used.toLocaleString()} used`}
				>
					<div class="pointer-events-none absolute inset-y-0 left-0 bg-primary-soft" style={`width:${((it.qty / maxQty) * 100).toFixed(1)}%`}></div>
					<span
						class="relative size-4 shrink-0 rounded-check border border-line {it.is_trans ? 'opacity-70' : ''}"
						style={`background:#${it.rgb ?? '000'}`}
					></span>
					<span
						class="relative min-w-0 flex-1 truncate text-sm {isGuess || similarIds.has(it.color_id) ? 'font-medium text-ink' : 'text-ink-muted'}"
						>{it.color_name}{#if isGuess}<span class="ml-1 text-info-ink">(the guess)</span>{/if}</span
					>
					<span class="num relative shrink-0 text-sm text-ink-muted">{fmtQty(it.qty)}</span>
				</li>
			{/each}
		</ul>
		{#if rows.length === 0}<p class="px-(--pad-panel) py-3 text-sm text-ink-muted">No colors match "{search}".</p>{/if}
	{/if}
</Panel>
