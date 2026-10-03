<!--
	docs/components.md#profiles. One part, laid out the same wherever a part is
	shown, so a list of them can be read at a glance: the picture, then the
	name, then the BrickLink ID in tabular figures, then the Rebrickable number
	only when it is a different one, then the color and the count. Everything
	is in the same place in every tile of a layout, and the picture's area is
	square and the same size, shown whole on whatever the tile sits on.

	`row` is a line of a list (a small picture beside the text, the count and
	`children` at the end); a row owns its side padding like any row in a flush
	panel, `padded={false}` inside a panel that already pads. `row` wraps
	`children` (a color select, a quantity field) under the text when its own
	width is under 40rem. `tile` is a square picture over its name, for a grid
	of parts; its name takes two lines so the ID under it stays in line.
	`quantity` alone is "×4"; with `found` it is a kit's progress, "3 / 6", and
	turns green when it is complete.

	With `href` or `onclick` the whole part is the target, named by its name;
	controls inside `children` still work (as in Card).

	<PartTile name="Brick 2 x 4" bricklinkId="3001" imgUrl={url} color={{ name: 'Red', rgb: 'C91A09' }} quantity={6} found={3} />
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Check from '@lucide/svelte/icons/check';
	import PartImage from './PartImage.svelte';
	import ColorChip from './ColorChip.svelte';
	import ProgressBar from './ProgressBar.svelte';

	let {
		name,
		imgUrl = null,
		fallbackImgUrl = null,
		bricklinkId = null,
		partNum = null,
		color = null,
		quantity = null,
		found = null,
		layout = 'row',
		padded = true,
		href,
		onclick,
		class: className = '',
		children
	}: {
		name: string;
		imgUrl?: string | null;
		// Tried when imgUrl fails (a render in a color that may not exist).
		fallbackImgUrl?: string | null;
		// The BrickLink ID: what a sorter reports a piece by.
		bricklinkId?: string | null;
		// The Rebrickable number; shown only when it is not the BrickLink ID.
		partNum?: string | null;
		// A swatch and the name; `rgb` is the catalog's six hex digits.
		color?: { name: string | null; rgb?: string | null } | null;
		quantity?: number | null;
		// A kit's progress: how many of `quantity` have been found.
		found?: number | null;
		layout?: 'row' | 'tile';
		// Row only: its own side padding (off inside a panel that already pads).
		padded?: boolean;
		href?: string;
		onclick?: () => void;
		class?: string;
		// Controls at its end, such as a quantity field.
		children?: Snippet;
	} = $props();

	// What stands in the ID's place: the BrickLink ID, then the Rebrickable
	// number when it differs (or alone, when the part has no BrickLink ID).
	const rebrickable = $derived(partNum && partNum !== bricklinkId ? partNum : null);
	const idTitle = $derived(
		[bricklinkId && `BrickLink ${bricklinkId}`, rebrickable && `Rebrickable ${rebrickable}`]
			.filter(Boolean)
			.join(', ')
	);
	const done = $derived(quantity != null && found != null && found >= quantity);
	const hasCount = $derived(quantity != null || found != null);

	// The target lies under the content and lets the pointer through to it,
	// except to the content's own controls (the way Card does).
	const target =
		'absolute inset-0 rounded-control transition-colors hover:bg-hover active:bg-pressed';
	const content =
		'pointer-events-none relative [&_a]:pointer-events-auto [&_button]:pointer-events-auto [&_input]:pointer-events-auto [&_label]:pointer-events-auto [&_select]:pointer-events-auto [&_summary]:pointer-events-auto [&_textarea]:pointer-events-auto';
</script>

{#snippet hit()}
	{#if href}
		<a {href} aria-label={name} class={target}></a>
	{:else if onclick}
		<button type="button" aria-label={name} {onclick} class={target}></button>
	{/if}
{/snippet}

{#snippet ids()}
	{#if bricklinkId}<span class="num">{bricklinkId}</span>{/if}
	{#if rebrickable}
		{' '}<span class="num whitespace-nowrap">{bricklinkId ? '· ' : ''}RB {rebrickable}</span>
	{/if}
{/snippet}

{#snippet count()}
	{#if found != null && quantity != null}
		<span
			class="num inline-flex items-center gap-1 text-sm whitespace-nowrap {done
				? 'text-success-ink'
				: 'text-ink'}"
		>
			{#if done}<Check size={14} class="shrink-0" />{/if}
			{found}<span class={done ? '' : 'text-ink-muted'}>/ {quantity}</span>
		</span>
	{:else if quantity != null}
		<span class="num text-sm whitespace-nowrap text-ink">×{quantity}</span>
	{:else if found != null}
		<span class="num text-sm whitespace-nowrap text-ink">{found}</span>
	{/if}
{/snippet}

{#if layout === 'tile'}
	<div class="relative isolate w-full min-w-0 {className}">
		{@render hit()}
		<div class="{content} flex flex-col gap-2">
			<PartImage src={imgUrl} fallback={fallbackImgUrl} class="aspect-square w-full" />
			<div class="min-w-0">
				<div class="line-clamp-2 h-10 text-sm font-medium break-words text-ink" title={name}>
					{name}
				</div>
				<div class="min-h-5 truncate text-sm text-ink-muted" title={idTitle}>{@render ids()}</div>
				{#if color}
					<div class="flex min-h-5 items-center text-sm text-ink-muted">
						<ColorChip name={color.name} rgb={color.rgb} />
					</div>
				{/if}
				{#if hasCount}
					<div class="flex min-h-5 items-center">
						{@render count()}
						{#if found != null && quantity != null && quantity > 0}
							<ProgressBar
								value={found}
								max={quantity}
								label="{name}: {found} of {quantity} found"
								tone={done ? 'success' : 'primary'}
							/>
						{/if}
					</div>
				{/if}
			</div>
			{#if children}<div class="flex flex-wrap items-center gap-2">{@render children()}</div>{/if}
		</div>
	</div>
{:else}
	<div class="@container relative isolate w-full min-w-0 {className}">
		{@render hit()}
		<div
			class="{content} flex flex-wrap items-center gap-x-3 gap-y-2 {padded
				? 'px-(--pad-panel) py-2'
				: ''}"
		>
			<div class="flex min-w-0 flex-1 items-center gap-3">
				<PartImage src={imgUrl} fallback={fallbackImgUrl} class="size-12 shrink-0" />
				<div class="min-w-0 flex-1">
					<div class="truncate text-sm font-medium text-ink" title={name}>{name}</div>
					{#if bricklinkId || rebrickable || color}
						<div class="flex min-w-0 items-center gap-x-3 text-sm text-ink-muted">
							{#if bricklinkId || rebrickable}
								<span class="flex shrink-0 gap-x-1.5" title={idTitle}>{@render ids()}</span>
							{/if}
							{#if color}<ColorChip name={color.name} rgb={color.rgb} />{/if}
						</div>
					{/if}
				</div>
				{#if hasCount}
					<div class="flex w-16 shrink-0 flex-col items-end gap-1">
						{@render count()}
						{#if found != null && quantity != null && quantity > 0}
							<ProgressBar
								value={found}
								max={quantity}
								label="{name}: {found} of {quantity} found"
								tone={done ? 'success' : 'primary'}
							/>
						{/if}
					</div>
				{/if}
			</div>
			{#if children}
				<div
					class="flex shrink-0 flex-wrap items-center gap-2 @max-[40rem]:basis-full @max-[40rem]:pl-15"
				>
					{@render children()}
				</div>
			{/if}
		</div>
	</div>
{/if}
