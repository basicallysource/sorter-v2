<!--
	What the part is sold in on BrickLink, most pieces first: the top ten, and
	the rest behind "All N". Every color is there, never filtered: an earlier
	version kept only solid colors near the guess and so hid that 98347 is sold
	almost only in Flat Silver and Pearl Dark Gray, and revealing the colors
	nobody would have thought of is the point. The rows are the likely-colors
	ranking's sale numbers, so this and the likely colors read one answer; the
	colors that ranking puts first (`likelyIds`) are in the ink, and a row picks
	its color like a likely color does. A section of the True color panel, beside
	the likely colors.
-->
<script lang="ts">
	import type { BrickLinkColor, LikelyColor } from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronUp from '@lucide/svelte/icons/chevron-up';

	const TOP = 10;

	let {
		palette,
		items,
		guessColorId,
		likelyIds = new Set<number>(),
		value = null,
		updatedAt,
		source = 'cache',
		loading = false,
		error = null,
		disabled = false,
		onpick
	}: {
		palette: BrickLinkColor[];
		// Colors with pieces for sale, most first.
		items: LikelyColor[];
		guessColorId: number | null;
		likelyIds?: Set<number>;
		// The chosen color.
		value?: number | null;
		updatedAt?: string | null;
		source?: 'live' | 'cache' | 'none';
		loading?: boolean;
		error?: string | null;
		disabled?: boolean;
		onpick: (id: number) => void;
	} = $props();

	let showAll = $state(false);

	const guess = $derived(palette.find((c) => c.id === guessColorId) ?? null);
	const guessSold = $derived(items.some((it) => it.color_id === guessColorId));
	const rows = $derived(showAll ? items : items.slice(0, TOP));
	const maxQty = $derived(Math.max(1, ...items.map((it) => it.qty ?? 0)));
	const asOf = $derived(updatedAt ? new Date(updatedAt).toLocaleDateString() : null);

	function fmtQty(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${Math.round(n / 1000)}k`;
		return String(n);
	}
</script>

<section class="flex min-w-0 flex-col gap-1.5" aria-busy={loading}>
	<div class="flex items-baseline justify-between gap-3">
		<h3 class="label">Sold on BrickLink</h3>
		{#if !loading && !error && items.length > 0}
			<span class="num text-xs text-ink-muted">{items.length} color{items.length === 1 ? '' : 's'}, {source === 'live' ? 'live' : (asOf ?? 'cached')}</span>
		{/if}
	</div>
	{#if loading}
		<div class="flex flex-col gap-1.5">
			{#each Array(6) as _, i (i)}<Skeleton class="h-4 w-full" />{/each}
		</div>
	{:else if error}
		<p class="text-sm text-danger-ink">{error}</p>
	{:else if items.length === 0}
		<p class="text-sm text-ink-muted">No BrickLink listings for this part.</p>
	{:else}
		<!-- Said outright: a guess that nobody sells is strong evidence against it,
		     and a row that is simply missing would hide that. -->
		{#if guess && !guessSold}<p class="text-sm text-warning-ink">No {guess.name} is for sale.</p>{/if}
		<div class="flex flex-col">
			{#each rows as it (it.color_id)}
				{@const on = it.color_id === value}
				{@const isGuess = it.color_id === guessColorId}
				<button
					type="button"
					aria-pressed={on}
					{disabled}
					onclick={() => onpick(it.color_id)}
					title={`${it.color_name} (${it.color_id}): ${(it.qty ?? 0).toLocaleString()} pieces in ${(it.lots ?? 0).toLocaleString()} lots`}
					class="relative flex min-w-0 items-center gap-2 overflow-hidden rounded-item px-1.5 py-0.5 text-left disabled:opacity-45 {on
						? 'bg-primary-soft'
						: 'hover:bg-hover'}"
				>
					{#if !on}
						<span class="pointer-events-none absolute inset-y-0 left-0 bg-track" style:width={`${(((it.qty ?? 0) / maxQty) * 100).toFixed(1)}%`}></span>
					{/if}
					<span
						aria-hidden="true"
						class="relative size-4 shrink-0 rounded-check border border-line-strong {it.is_trans ? 'opacity-70' : ''}"
						style:background-color={`#${it.rgb ?? '000'}`}
					></span>
					<span
						class="relative min-w-0 flex-1 truncate text-sm {on
							? 'font-medium text-primary-ink'
							: isGuess || likelyIds.has(it.color_id)
								? 'text-ink'
								: 'text-ink-muted'}">{it.color_name}</span
					>
					{#if isGuess}<span class="relative shrink-0 text-xs text-info-ink">the guess</span>{/if}
					<span class="num relative shrink-0 text-xs text-ink-muted">{fmtQty(it.qty ?? 0)}</span>
					{#if on}<Check size={14} class="relative shrink-0 text-primary-ink" />{/if}
				</button>
			{/each}
		</div>
		{#if items.length > TOP}
			<div>
				<Button size="sm" variant="ghost" icon={showAll ? ChevronUp : ChevronDown} aria-expanded={showAll} onclick={() => (showAll = !showAll)}
					>{showAll ? `The top ${TOP}` : `All ${items.length}`}</Button
				>
			</div>
		{/if}
	{/if}
</section>
