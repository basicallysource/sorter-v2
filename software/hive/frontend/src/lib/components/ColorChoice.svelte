<!--
	docs/components.md#color-review. Picking a piece's true LEGO color: the
	colors it is most likely to be, as a compact grid of swatches with their
	names, best first; then a search of every color by name or number. The
	search lists its matches as it is typed (Enter picks the first), and "All
	colors" lists the whole palette; otherwise nothing is listed under it. No
	list here scrolls on its own: what is shown is part of the page.

	`likely` is the ranking, each color with the numbers behind its place
	(how near it is to what was predicted, its share of the part's pieces for
	sale on BrickLink). A tile's second line is the share for sale (how near
	it is shows in the swatch itself), or how near it is in words when there
	are no sale numbers; its tooltip has every number. `marks` names the
	predicted colors ("Predicted 82%", "The guess"). A marked color and the
	chosen one (`value`, in the primary's tint) are always in the grid.
	`likely` is null while the ranking loads (the grid holds its place), and
	`note` is one line under the heading that says how the grid was ranked
	when that is not the usual way. `aside` sits beside the likely colors and
	the search, or under them where the block is narrower than 36rem: Hive
	puts the part's top colors sold on BrickLink there.

	<ColorChoice {palette} likely={ranked} value={chosen}
		marks={{ 4: 'Predicted 82%' }} onpick={(id) => (chosen = id)} />
-->
<script module lang="ts">
	export type PaletteColor = { id: number; name: string; rgb: string | null; is_trans?: boolean };

	// One color in a ranking (Hive's likely-colors response).
	export type LikelyColor = {
		color_id: number;
		color_name?: string | null;
		rgb?: string | null;
		is_trans?: boolean;
		rank?: number;
		score: number;
		closeness: number;
		likelihood: number;
		distance: number | null;
		hue_diff: number | null;
		predicted?: boolean;
		predicted_score?: number | null;
		qty: number | null;
		lots: number | null;
		share: number | null;
		known_in?: boolean;
	};

	// How near a color is to the prediction, in a word.
	export function nearText(distance: number | null): string | null {
		if (distance == null) return null;
		if (distance < 10) return 'Very close';
		if (distance < 22) return 'Close';
		if (distance < 40) return 'Near';
		return 'Far';
	}

	// Its share of the part's pieces for sale, or null with no sale data.
	export function saleText(c: Pick<LikelyColor, 'qty' | 'share' | 'known_in'>): string | null {
		if (c.qty == null) return null;
		if (c.qty <= 0) return c.known_in ? 'Listed, none for sale' : 'None for sale';
		if (c.share == null) return 'For sale';
		return c.share >= 0.01 ? `${Math.round(c.share * 100)}% for sale` : '<1% for sale';
	}

	// Every number behind a color's place, for its tooltip.
	export function likelyTitle(name: string, c: LikelyColor): string {
		const parts = [`${name} (${c.color_id})`];
		if (c.qty != null) {
			parts.push(
				c.qty > 0
					? `${c.qty.toLocaleString()} pieces for sale in ${(c.lots ?? 0).toLocaleString()} lots${c.share != null ? `, ${(c.share * 100).toFixed(1)}% of the part's` : ''}`
					: c.known_in
						? 'listed in this color, none for sale'
						: 'none for sale'
			);
		}
		if (c.distance != null) {
			parts.push(
				`${c.distance.toFixed(1)} from the prediction${c.hue_diff != null ? `, ${Math.round(c.hue_diff)}° of hue apart` : ''}`
			);
		}
		parts.push(
			`score ${c.score.toFixed(3)}: closeness ${c.closeness.toFixed(2)} × likelihood ${c.likelihood.toFixed(2)}`
		);
		return parts.join('; ');
	}
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronUp from '@lucide/svelte/icons/chevron-up';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import Button from './Button.svelte';
	import Input from './Input.svelte';
	import Skeleton from './Skeleton.svelte';
	import { swatchColor } from './ColorChip.svelte';

	let {
		palette,
		likely = null,
		value = null,
		marks = {},
		count = 12,
		note = null,
		disabled = false,
		aside,
		onpick
	}: {
		palette: PaletteColor[];
		likely?: LikelyColor[] | null;
		value?: number | null;
		// Color id -> what marks it ("Predicted 82%").
		marks?: Record<number, string>;
		// How many tiles the grid shows.
		count?: number;
		note?: string | null;
		disabled?: boolean;
		// Beside the likely colors and the search (under them where there is no room).
		aside?: Snippet;
		onpick: (id: number) => void;
	} = $props();

	// Tiles of 9rem or more, and at least two to a row however narrow.
	const GRID = 'repeat(auto-fill, minmax(min(9rem, calc(50% - 0.0625rem)), 1fr))';
	// The colors the search lists, in as many columns as fit.
	const LIST = 'repeat(auto-fill, minmax(min(10rem, 100%), 1fr))';

	let query = $state('');
	let showAll = $state(false);

	const byId = $derived(new Map(palette.map((c) => [c.id, c])));

	// The best `count`, with every marked color and the chosen one kept in: a
	// color that must show but is past the cut takes the place of the last one
	// that need not, in rank order.
	const tiles = $derived.by(() => {
		if (!likely) return [];
		const kept = (id: number) => marks[id] != null || id === value;
		const known = likely.filter((c) => byId.has(c.color_id));
		const top = known.slice(0, count);
		const missing = known.slice(count).filter((c) => kept(c.color_id));
		for (const extra of missing) {
			let drop = top.length - 1;
			while (drop >= 0 && kept(top[drop].color_id)) drop--;
			if (drop < 0) break;
			top.splice(drop, 1);
			top.push(extra);
		}
		return top.sort((a, b) => known.indexOf(a) - known.indexOf(b));
	});

	const searching = $derived(query.trim() !== '');
	const listed = $derived.by(() => {
		const q = query.trim().toLowerCase();
		if (!q) return showAll ? palette : [];
		return palette.filter((c) => c.name.toLowerCase().includes(q) || String(c.id) === q);
	});

	// A pick from the list closes it: the chosen color shows in the grid.
	function pick(id: number) {
		query = '';
		showAll = false;
		onpick(id);
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key !== 'Enter' || !searching || listed.length === 0 || disabled) return;
		event.preventDefault();
		pick(listed[0].id);
	}
</script>

<div class="@container">
	<div class="grid gap-x-6 gap-y-3 {aside ? '@xl:grid-cols-2' : ''}">
		<div class="flex min-w-0 flex-col gap-3">
			<section class="flex min-w-0 flex-col gap-1.5" aria-busy={likely == null}>
				<div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
					<h3 class="label">Likely colors</h3>
					{#if note}<p class="text-sm text-ink-muted">{note}</p>{/if}
				</div>
				<div class="grid gap-0.5" style:grid-template-columns={GRID}>
					{#if likely == null}
						{#each Array(Math.min(count, 6)) as _, i (i)}
							<div class="flex items-center gap-2 px-1.5 py-1">
								<Skeleton class="size-6 shrink-0" />
								<div class="flex flex-1 flex-col gap-1">
									<Skeleton class="h-3.5 w-20" /><Skeleton class="h-3 w-14" />
								</div>
							</div>
						{/each}
					{:else}
						{#each tiles as c (c.color_id)}
							{@const color = byId.get(c.color_id)!}
							{@const on = c.color_id === value}
							{@const mark = marks[c.color_id]}
							{@const facts = saleText(c) ?? nearText(c.distance)}
							<button
								type="button"
								aria-pressed={on}
								title={likelyTitle(color.name, c)}
								{disabled}
								onclick={() => onpick(c.color_id)}
								class="flex min-w-0 items-center gap-2 rounded-item px-1.5 py-1 text-left disabled:opacity-45
									{on ? 'bg-primary-soft' : 'hover:bg-hover'}"
							>
								<span
									aria-hidden="true"
									class="size-6 shrink-0 rounded-check border border-line-strong"
									style:background-color={swatchColor(color.rgb)}
								></span>
								<span class="flex min-w-0 flex-1 flex-col">
									<span
										class="truncate text-sm leading-snug {on
											? 'font-medium text-primary-ink'
											: 'text-ink'}">{color.name}</span
									>
									{#if mark}
										<span class="flex min-w-0 items-center gap-1 text-xs text-info-ink"
											><Sparkles size={12} class="shrink-0" /><span class="truncate">{mark}</span
											></span
										>
									{:else}
										<span class="num truncate text-xs text-ink-muted">{facts || ' '}</span>
									{/if}
								</span>
							</button>
						{:else}
							<p class="col-span-full py-2 text-sm text-ink-muted">No ranking for this piece.</p>
						{/each}
					{/if}
				</div>
			</section>
			<section class="flex flex-col gap-1.5">
				<div class="flex items-center gap-2">
					<Input
						type="search"
						size="sm"
						class="min-w-0 flex-1"
						aria-label="Search every color"
						placeholder="Search {palette.length} colors"
						bind:value={query}
						{onkeydown}
					/>
					<Button
						size="sm"
						variant="ghost"
						icon={showAll ? ChevronUp : ChevronDown}
						aria-expanded={showAll}
						onclick={() => (showAll = !showAll)}>All colors</Button
					>
				</div>
				{#if searching || showAll}
					<div class="grid gap-0.5" style:grid-template-columns={LIST}>
						{#each listed as color (color.id)}
							{@const on = color.id === value}
							{@const mark = marks[color.id]}
							<button
								type="button"
								aria-pressed={on}
								title={`${color.name} (${color.id})`}
								{disabled}
								onclick={() => pick(color.id)}
								class="flex min-w-0 items-center gap-2 rounded-item px-1.5 py-1 text-left disabled:opacity-45
									{on ? 'bg-primary-soft' : 'hover:bg-hover'}"
							>
								<span
									aria-hidden="true"
									class="size-4 shrink-0 rounded-check border border-line-strong"
									style:background-color={swatchColor(color.rgb)}
								></span>
								<span
									class="min-w-0 flex-1 truncate text-sm {on
										? 'font-medium text-primary-ink'
										: 'text-ink'}">{color.name}</span
								>
								{#if mark}
									<span class="flex shrink-0 items-center gap-1 text-xs text-info-ink"
										><Sparkles size={12} />{mark}</span
									>
								{/if}
								<span class="num shrink-0 text-xs text-ink-muted">{color.id}</span>
								{#if on}<Check size={14} class="shrink-0 text-primary-ink" />{/if}
							</button>
						{:else}
							<p class="col-span-full px-1.5 py-1 text-sm text-ink-muted">
								{palette.length === 0
									? 'The color list has not loaded.'
									: `No color matches "${query.trim()}".`}
							</p>
						{/each}
					</div>
				{/if}
			</section>
		</div>
		{#if aside}
			<div class="min-w-0">{@render aside()}</div>
		{/if}
	</div>
</div>
