<script lang="ts">
	import type { InfoRow } from './types';

	// Titled key/value card used for every "facts about this piece" panel on the
	// piece detail page. Both the live (in-memory) and disk-fallback views feed
	// the same component so the two can't drift apart visually.
	let {
		title,
		rows,
		image = null,
		imageAlt = '',
		onImageClick
	}: {
		title: string;
		rows: InfoRow[];
		image?: string | null;
		imageAlt?: string;
		onImageClick?: () => void;
	} = $props();
</script>

<section class="flex flex-col border border-border bg-surface">
	<div class="border-b border-border bg-bg px-3 py-2 text-sm font-medium text-text">
		{title}
	</div>
	<div class="grid grid-cols-[minmax(0,1fr)_auto]">
		<div class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 px-3 py-3 text-sm">
			{#each rows as row (row.label)}
				<span class="text-text-muted">{row.label}</span>
				<span class={`${row.mono ? 'font-mono ' : ''}${row.valueClass ?? 'text-text'}`}>
					{row.value}
				</span>
			{/each}
		</div>
		{#if image}
			<button
				type="button"
				class="flex items-center justify-center border-l border-border bg-surface p-3 hover:bg-bg"
				onclick={onImageClick}
			>
				<img
					src={image}
					alt={imageAlt}
					class="h-24 w-24 cursor-zoom-in object-contain"
					loading="lazy"
				/>
			</button>
		{/if}
	</div>
</section>
