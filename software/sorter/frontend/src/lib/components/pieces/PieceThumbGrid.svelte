<script lang="ts" generics="T">
	import type { Snippet } from 'svelte';
	import type { Thumb } from './types';

	// Shared thumbnail gallery for every image grid on the piece detail page
	// (stored images, captured crops, possible upstream matches). `items` keeps
	// the caller's own row type so the `overlay` snippet can render badges that
	// need the original record.
	//
	// `items-start` on the grid matters: without it the grid stretches each tile
	// to the tallest row, which blew the square crops up into tall rectangles.
	let {
		items,
		minPx = 120,
		gridClass = '',
		onZoom,
		overlay
	}: {
		items: Thumb<T>[];
		minPx?: number;
		gridClass?: string;
		onZoom: (item: Thumb<T>) => void;
		overlay?: Snippet<[Thumb<T>]>;
	} = $props();
</script>

<div
	class={`grid items-start gap-1.5 ${gridClass}`}
	style={`grid-template-columns: repeat(auto-fill, minmax(${minPx}px, 1fr));`}
>
	{#each items as item (item.key)}
		<button
			type="button"
			class={`flex flex-col bg-bg text-left hover:border-primary/70 ${
				item.used ? 'border-2 border-primary' : 'border border-border'
			}`}
			title={item.title}
			onclick={() => onZoom(item)}
		>
			<div class="relative aspect-square w-full bg-white">
				<img
					src={item.src}
					alt={item.alt ?? ''}
					class="h-full w-full cursor-zoom-in object-contain"
					loading="lazy"
				/>
				{#if overlay}
					{@render overlay(item)}
				{/if}
			</div>
			{#if item.caption || item.captionRight}
				<div class="flex items-center justify-between gap-2 px-2 py-1.5 text-xs text-text-muted">
					<span class="truncate">{item.caption ?? ''}</span>
					{#if item.captionRight}
						<span class="shrink-0 tabular-nums">{item.captionRight}</span>
					{/if}
				</div>
			{/if}
		</button>
	{/each}
</div>
