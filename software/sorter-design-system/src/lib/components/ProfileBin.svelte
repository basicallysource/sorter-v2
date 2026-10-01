<!--
	docs/components.md#profiles. One bin of a sorting profile, as a card or as
	a row. The card is what a person needs to know about where pieces go: its
	picture (a color bin shows its color, a kit its picture), its place in the
	order and its name, what kind of bin it is (Rule, Kit, Category, Color,
	Everything else), how many parts it takes and in how many colors when it
	limits them, its conditions in words, example parts only when asked
	(`examples`), and what is wrong with it in the warning tone. The row is one line of that, for a long
	list of bins: the place, the picture, the name, how many parts, the kind,
	and a kit's progress.

	Every bin of one profile looks the same, so a stack of them, one to a line,
	can be read at a glance. A bin from a version saved before bins were described has only a
	name; it shows as a plain, name-only bin. The whole bin is the target when
	it has `href` or `onclick`, like a Card (controls inside still work).
	`plane="well"` for a card on a dialog, which is itself a surface.

	<ProfileBin {bin} number={3} warnings={warnings.get(id)} href="/profiles/{id}/bins/{id}" />
-->
<script module lang="ts">
	import type { BinConditions } from './ConditionList.svelte';

	// What Hive sends for a bin (the ProfileBin types in Hive's api.ts); the
	// fields of a bin saved before bins were described are all optional.
	export interface BinSample {
		// BrickLink ID (what a sorter reports), and the Rebrickable number.
		part_num: string;
		rb_part_num?: string | null;
		name: string;
		img_url: string | null;
		// Tried when img_url fails: img_url may be a render in the bin's color.
		fallback_img_url?: string | null;
		color_name?: string | null;
		quantity?: number | null;
	}

	export interface Bin {
		name: string;
		kind?: 'rule' | 'kit' | 'fallback' | 'default' | null;
		image_url?: string | null;
		image_fallback_url?: string | null;
		conditions?: BinConditions;
		// Parts the bin takes (null for a color bin: that depends on the pile).
		part_count?: number | null;
		// A rule that takes any part (it tests only colors, or nothing): its
		// part_count is only how many parts are known in those colors.
		any_part?: boolean;
		// When a rule takes only some colors.
		color_count?: number;
		colors?: Array<{ id: string; name: string | null; rgb: string | null }>;
		samples?: BinSample[];
		kit?: { line_count: number; total_quantity: number };
		// A color bin's color.
		rgb?: string | null;
	}
</script>

<script lang="ts">
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Check from '@lucide/svelte/icons/check';
	import Boxes from '@lucide/svelte/icons/boxes';
	import Badge from './Badge.svelte';
	import ProgressBar from './ProgressBar.svelte';
	import PartImage from './PartImage.svelte';
	import PartTile from './PartTile.svelte';
	import ConditionList from './ConditionList.svelte';
	import { swatchColor } from './ColorChip.svelte';

	let {
		bin,
		number,
		warnings = [],
		progress = null,
		selected = false,
		onclick,
		href,
		layout = 'card',
		plane = 'surface',
		examples = 0,
		class: className = ''
	}: {
		bin: Bin;
		// Its place in the order: the first rule that takes a piece wins.
		number?: number;
		warnings?: string[];
		// A kit's progress, in pieces.
		progress?: { found: number; needed: number } | null;
		selected?: boolean;
		onclick?: () => void;
		href?: string;
		layout?: 'card' | 'row';
		// The fill of a card: a dialog is a surface already, so a card on one is a well.
		plane?: 'surface' | 'well';
		// Most example parts a card shows.
		examples?: number;
		class?: string;
	} = $props();

	const isColor = $derived(bin.kind === 'fallback' && 'rgb' in bin);
	// A bin saved before bins were described: a name, and nothing to picture.
	const plain = $derived(!bin.kind && !bin.image_url);
	const label = $derived.by(() => {
		if (bin.kind === 'rule') return 'Rule';
		if (bin.kind === 'kit') return 'Kit';
		if (bin.kind === 'fallback') return isColor ? 'Color' : 'Category';
		if (bin.kind === 'default') return 'Everything else';
		return null;
	});
	// "Everything else" under the name "Everything else" says it twice.
	const showLabel = $derived(label && label.toLowerCase() !== (bin.name ?? '').toLowerCase());

	function plural(n: number, one: string, many = `${one}s`) {
		return `${n.toLocaleString('en-US')} ${n === 1 ? one : many}`;
	}

	// How much the bin takes, in words.
	const summary = $derived.by(() => {
		if (bin.kind === 'kit') {
			const lines = bin.kit?.line_count ?? bin.part_count;
			if (lines == null) return null;
			const pieces = bin.kit?.total_quantity;
			return pieces == null
				? plural(lines, 'part')
				: `${plural(lines, 'part')} · ${plural(pieces, 'piece')}`;
		}
		if (isColor) return 'Any part in this color';
		if (bin.any_part) {
			// How many parts are known to come in those colors is not what it takes.
			const only = bin.colors?.[0]?.name;
			if (bin.color_count === 1 && only) return `Any part in ${only}`;
			return bin.color_count ? `Any part in ${plural(bin.color_count, 'color')}` : 'Any part';
		}
		if (bin.part_count == null) return null;
		if (bin.part_count === 0) return 'No parts';
		const parts = plural(bin.part_count, 'part');
		return bin.color_count ? `${parts} in ${plural(bin.color_count, 'color')}` : parts;
	});

	const exampleParts = $derived((bin.samples ?? []).slice(0, examples));
	const color = $derived(isColor ? swatchColor(bin.rgb) : null);
	const fill = $derived(selected ? 'bg-primary-soft' : plane === 'well' ? 'bg-well' : 'bg-surface');

	const target =
		'absolute inset-0 rounded-panel transition-colors hover:bg-hover active:bg-pressed';
	const content =
		'pointer-events-none relative [&_a]:pointer-events-auto [&_button]:pointer-events-auto [&_input]:pointer-events-auto [&_label]:pointer-events-auto [&_select]:pointer-events-auto [&_summary]:pointer-events-auto [&_textarea]:pointer-events-auto';
</script>

{#snippet hit()}
	{#if href}
		<a {href} aria-label={bin.name} aria-current={selected ? 'true' : undefined} class={target}></a>
	{:else if onclick}
		<button
			type="button"
			aria-label={bin.name}
			aria-current={selected ? 'true' : undefined}
			{onclick}
			class={target}
		></button>
	{/if}
{/snippet}

<!-- A color bin is its color; the rest are their picture, or a quiet blank. -->
{#snippet art(size: string)}
	{#if isColor}
		<span
			aria-hidden="true"
			class="block shrink-0 rounded-control border border-line-strong {size} {color
				? ''
				: 'bg-hover'}"
			style:background-color={color}
		></span>
	{:else if bin.kind === 'default'}
		<span
			aria-hidden="true"
			class="flex shrink-0 items-center justify-center rounded-control bg-hover text-ink-faint {size}"
		>
			<Boxes size={layout === 'row' ? 18 : 24} />
		</span>
	{:else}
		<PartImage src={bin.image_url} fallback={bin.image_fallback_url} class="shrink-0 {size}" />
	{/if}
{/snippet}

{#snippet kind()}
	{#if showLabel}<Badge>{label}</Badge>{/if}
{/snippet}

{#if layout === 'row'}
	<div class="relative isolate w-full min-w-0 {fill} {className}">
		{@render hit()}
		<div class="{content} flex items-center gap-3 px-(--pad-panel) py-2">
			{#if number != null}
				<span class="num w-7 shrink-0 text-right text-sm text-ink-muted">{number}</span>
			{/if}
			{#if !plain}{@render art('size-10')}{/if}
			<div class="min-w-0 flex-1">
				<div class="truncate text-sm font-medium text-ink" title={bin.name}>{bin.name}</div>
				<!-- Down a list of colors, "any part in this color" is said by every row. -->
				{#if summary && !isColor}<div class="truncate text-sm text-ink-muted">{summary}</div>{/if}
			</div>
			{#if progress && progress.needed > 0}
				{@const complete = progress.found >= progress.needed}
				<div class="flex shrink-0 flex-col items-end gap-1 sm:w-24">
					<span
						class="num inline-flex items-center gap-1 text-sm whitespace-nowrap {complete
							? 'text-success-ink'
							: 'text-ink'}"
					>
						{#if complete}<Check size={14} class="shrink-0" />{/if}
						{progress.found.toLocaleString('en-US')} / {progress.needed.toLocaleString('en-US')}
					</span>
					<div class="hidden w-full sm:block">
						<ProgressBar
							value={progress.found}
							max={progress.needed}
							label="{bin.name}: {progress.found} of {progress.needed} found"
							tone={complete ? 'success' : 'primary'}
						/>
					</div>
				</div>
			{/if}
			{#if warnings.length > 0}
				<span class="shrink-0" title={warnings.join('\n')}>
					<Badge tone="warning">{plural(warnings.length, 'warning')}</Badge>
				</span>
			{/if}
			<span class="hidden shrink-0 sm:inline-flex">{@render kind()}</span>
		</div>
	</div>
{:else}
	<div
		class="@container relative isolate flex w-full min-w-0 flex-col rounded-panel {fill} {className}"
	>
		{@render hit()}
		<div class="{content} flex min-h-0 flex-1 flex-col gap-3 p-(--pad-panel)">
			<div class="flex items-start gap-3">
				{#if !plain}{@render art('size-14')}{/if}
				<div class="min-w-0 flex-1">
					<div class="flex items-start justify-between gap-2">
						<div class="flex min-w-0 items-baseline gap-2">
							{#if number != null}
								<span class="num shrink-0 text-base font-medium text-ink-muted">{number}</span>
							{/if}
							<h3
								class="line-clamp-2 min-w-0 text-base font-semibold break-words text-ink"
								title={bin.name}
							>
								{bin.name}
							</h3>
						</div>
						{#if showLabel}<div class="mt-0.5 shrink-0">{@render kind()}</div>{/if}
					</div>
					{#if summary}<p class="mt-0.5 text-sm text-ink-muted">{summary}</p>{/if}
				</div>
			</div>

			{#if progress && progress.needed > 0}
				{@const complete = progress.found >= progress.needed}
				<div class="flex flex-col gap-1.5">
					<div class="flex items-center justify-between gap-2 text-sm">
						<span class="text-ink-muted">Found</span>
						<span
							class="num inline-flex items-center gap-1 {complete
								? 'text-success-ink'
								: 'text-ink'}"
						>
							{#if complete}<Check size={14} class="shrink-0" />{/if}
							{progress.found.toLocaleString('en-US')} of {progress.needed.toLocaleString('en-US')}
						</span>
					</div>
					<ProgressBar
						value={progress.found}
						max={progress.needed}
						label="{bin.name}: {progress.found} of {progress.needed} found"
						tone={complete ? 'success' : 'primary'}
					/>
				</div>
			{/if}

			{#if bin.conditions}
				<ConditionList conditions={bin.conditions} limit={4} />
			{/if}

			{#if exampleParts.length > 0}
				<div class="flex flex-col gap-1.5">
					<div class="text-sm font-medium text-ink-muted">Examples</div>
					<!-- A kit's parts carry a color and a count, so they get the width of a line. -->
					<div class="grid gap-x-4 gap-y-2 {bin.kind === 'kit' ? '' : '@min-[26rem]:grid-cols-2'}">
						{#each exampleParts as sample, i (i)}
							<PartTile
								padded={false}
								name={sample.name}
								imgUrl={sample.img_url}
								fallbackImgUrl={sample.fallback_img_url}
								bricklinkId={sample.part_num}
								partNum={sample.rb_part_num}
								color={sample.color_name ? { name: sample.color_name } : null}
								quantity={sample.quantity}
							/>
						{/each}
					</div>
				</div>
			{/if}

			{#if warnings.length > 0}
				<ul class="mt-auto flex flex-col gap-1.5 rounded-control bg-warning-soft px-3 py-2">
					{#each warnings as warning, i (i)}
						<li class="flex items-start gap-2 text-sm text-ink">
							<TriangleAlert size={16} class="mt-0.5 shrink-0 text-warning-ink" />
							<span class="min-w-0">{warning}</span>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	</div>
{/if}
