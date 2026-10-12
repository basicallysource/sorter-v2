<!--
	docs/components.md#color-review. Picking a piece's true LEGO color: the
	colors it is most likely to be, as a grid of swatches with their names,
	best first; then every color, behind a search by name or number.

	`likely` is the ranking, each color with the numbers behind its place
	(how near it is to what was predicted, its share of the part's pieces for
	sale on BrickLink). A tile's second line is the share for sale (how near
	it is shows in the swatch itself), or how near it is in words when there
	are no sale numbers; its tooltip has every number. `marks` names the
	predicted colors ("Predicted 82%", "The guess"): a marked color is always
	in the grid, with the mark in place of its numbers. `value` is the chosen
	color, in the primary's tint (and a check in the list). `likely` is null
	while the ranking loads (the grid holds its place), and `note` is one line
	under the heading that says how the grid was ranked when that is not the
	usual way. `fill` lets the list of every color take the height left in a
	column instead of its own.

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
	import Check from '@lucide/svelte/icons/check';
	import Sparkles from '@lucide/svelte/icons/sparkles';
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
		fill = false,
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
		fill?: boolean;
		onpick: (id: number) => void;
	} = $props();

	// Tiles of 10.5rem or more, and at least two to a row however narrow, so a
	// phone shows six rows of likely colors rather than twelve.
	const GRID = 'repeat(auto-fill, minmax(min(10.5rem, calc(50% - 0.125rem)), 1fr))';

	let query = $state('');

	const byId = $derived(new Map(palette.map((c) => [c.id, c])));

	// The best `count`, with every marked color kept in: a marked color past
	// the cut takes the place of the last unmarked one, in rank order.
	const tiles = $derived.by(() => {
		if (!likely) return [];
		const known = likely.filter((c) => byId.has(c.color_id));
		const top = known.slice(0, count);
		const missing = known.slice(count).filter((c) => marks[c.color_id] != null);
		for (const extra of missing) {
			let drop = top.length - 1;
			while (drop >= 0 && marks[top[drop].color_id] != null) drop--;
			if (drop < 0) break;
			top.splice(drop, 1);
			top.push(extra);
		}
		return top.sort((a, b) => known.indexOf(a) - known.indexOf(b));
	});

	const matches = $derived.by(() => {
		const q = query.trim().toLowerCase();
		if (!q) return palette;
		return palette.filter((c) => c.name.toLowerCase().includes(q) || String(c.id) === q);
	});
</script>

<div class="flex min-h-0 flex-col gap-4 {fill ? 'h-full' : ''}">
	<section class="flex flex-col gap-2" aria-busy={likely == null}>
		<div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
			<h3 class="label">Likely colors</h3>
			{#if note}<p class="text-sm text-ink-muted">{note}</p>{/if}
		</div>
		<div class="grid gap-1" style:grid-template-columns={GRID}>
			{#if likely == null}
				{#each Array(Math.min(count, 6)) as _, i (i)}
					<div class="flex items-center gap-3 px-2 py-2">
						<Skeleton class="size-8 shrink-0" />
						<div class="flex flex-1 flex-col gap-1.5">
							<Skeleton class="h-3.5 w-24" /><Skeleton class="h-3 w-16" />
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
						class="flex min-w-0 items-center gap-3 rounded-item px-2 py-2 text-left disabled:opacity-45
							{on ? 'bg-primary-soft' : 'hover:bg-hover'}"
					>
						<span
							aria-hidden="true"
							class="size-8 shrink-0 rounded-check border border-line-strong"
							style:background-color={swatchColor(color.rgb)}
						></span>
						<span class="flex min-w-0 flex-1 flex-col">
							<span
								class="line-clamp-2 text-sm leading-snug {on
									? 'font-medium text-primary-ink'
									: 'text-ink'}">{color.name}</span
							>
							{#if mark}
								<span class="flex min-w-0 items-start gap-1 text-xs text-info-ink"
									><Sparkles size={12} class="mt-px shrink-0" /><span>{mark}</span></span
								>
							{:else}
								<span class="num truncate text-xs text-ink-muted">{facts || '\u00a0'}</span>
							{/if}
						</span>
					</button>
				{:else}
					<p class="col-span-full py-2 text-sm text-ink-muted">No ranking for this piece.</p>
				{/each}
			{/if}
		</div>
	</section>

	<section class="flex min-h-0 flex-col gap-2 {fill ? 'flex-1' : ''}">
		<h3 class="label">Every color</h3>
		<Input
			type="search"
			aria-label="Search the colors"
			placeholder="Search {palette.length} colors by name or number"
			bind:value={query}
		/>
		<div class="flex min-h-0 flex-col overflow-y-auto {fill ? 'flex-1' : 'max-h-64'}">
			{#each matches as color (color.id)}
				{@const on = color.id === value}
				{@const mark = marks[color.id]}
				<button
					type="button"
					aria-pressed={on}
					{disabled}
					onclick={() => onpick(color.id)}
					class="flex min-h-(--size-menu-item) shrink-0 items-center gap-2 rounded-item px-2 text-left disabled:opacity-45
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
					{#if on}<Check size={16} class="shrink-0 text-primary-ink" />{/if}
				</button>
			{:else}
				<p class="px-2 py-3 text-sm text-ink-muted">
					{palette.length === 0
						? 'The color list has not loaded.'
						: `No color matches "${query.trim()}".`}
				</p>
			{/each}
		</div>
	</section>
</div>
