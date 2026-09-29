<script lang="ts">
	import Crop from '@lucide/svelte/icons/crop';
	import Expand from '@lucide/svelte/icons/expand';
	import SendToBack from '@lucide/svelte/icons/send-to-back';
	import Shapes from '@lucide/svelte/icons/shapes';

	let {
		annotated = $bindable(true),
		cropped = $bindable(false),
		zones = $bindable(true),
		fullscreen = $bindable(false),
		showAnnotations = true,
		showCrop = false,
		showZones = false,
		showFullscreen = false,
		disabled = false
	}: {
		annotated?: boolean;
		cropped?: boolean;
		zones?: boolean;
		fullscreen?: boolean;
		showAnnotations?: boolean;
		showCrop?: boolean;
		showZones?: boolean;
		showFullscreen?: boolean;
		disabled?: boolean;
	} = $props();

	const hasAny = $derived(
		showAnnotations || showCrop || showZones || showFullscreen
	);
</script>

<!-- Toggles over a camera picture, in its dark subtree: a scrim when off,
     the primary when on. -->
{#snippet toggle(Icon: typeof SendToBack, active: boolean, label: string, onToggle: () => void)}
	<button
		type="button"
		{disabled}
		onclick={onToggle}
		title={label}
		aria-pressed={active}
		aria-label={label}
		class="pointer-events-auto inline-flex size-(--size-control-sm) items-center justify-center rounded-button transition-colors disabled:pointer-events-none disabled:opacity-45 {active
			? 'bg-primary text-on-primary hover:bg-primary-hover'
			: 'bg-scrim text-ink-muted hover:text-ink'}"
	>
		<Icon size={14} />
	</button>
{/snippet}

{#if hasAny}
	<div class="pointer-events-none absolute top-2 right-2 z-10 flex gap-1">
		{#if showAnnotations}
			{@render toggle(
				SendToBack,
				annotated,
				annotated ? 'Hide annotations' : 'Show annotations',
				() => (annotated = !annotated)
			)}
		{/if}
		{#if showZones}
			{@render toggle(Shapes, zones, zones ? 'Hide zones' : 'Show zones', () => (zones = !zones))}
		{/if}
		{#if showCrop}
			{@render toggle(
				Crop,
				cropped,
				cropped ? 'Show the full frame' : 'Show the cropped view',
				() => (cropped = !cropped)
			)}
		{/if}
		{#if showFullscreen}
			{@render toggle(
				Expand,
				fullscreen,
				fullscreen ? 'Leave full screen' : 'Full screen',
				() => (fullscreen = !fullscreen)
			)}
		{/if}
	</div>
{/if}
