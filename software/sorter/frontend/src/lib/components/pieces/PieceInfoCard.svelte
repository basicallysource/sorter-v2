<script lang="ts">
	import Panel from '$lib/components/ui/Panel.svelte';
	import type { InfoRow } from './types';

	// Titled key/value panel used for every "facts about this piece" section on
	// the piece detail page. Both the live (in-memory) and disk-fallback views
	// feed the same component so the two can't drift apart visually.
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

<Panel {title} flush>
	<div class="flex items-start gap-4 {image ? 'pr-(--pad-panel) pb-(--pad-panel)' : ''}">
		<dl class="min-w-0 flex-1 divide-y divide-line text-sm">
			{#each rows as row (row.label)}
				<div class="flex items-baseline justify-between gap-6 px-(--pad-panel) py-2.5">
					<dt class="shrink-0 text-ink-muted">{row.label}</dt>
					<dd class="min-w-0 truncate text-right {row.mono ? 'font-mono' : ''} {row.valueClass ?? 'text-ink'}">
						{row.value}
					</dd>
				</div>
			{/each}
		</dl>
		{#if image}
			<button
				type="button"
				class="shrink-0 rounded-control p-2 transition-colors hover:bg-hover"
				aria-label="Enlarge the {imageAlt}"
				onclick={onImageClick}
			>
				<img src={image} alt={imageAlt} class="size-24 rounded-item object-contain" loading="lazy" />
			</button>
		{/if}
	</div>
</Panel>
