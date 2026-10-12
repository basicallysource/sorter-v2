<script lang="ts">
	import SendToBack from '@lucide/svelte/icons/send-to-back';
	import Shapes from '@lucide/svelte/icons/shapes';

	let {
		annotated = $bindable(true),
		zones = $bindable(true),
		showAnnotations = true,
		showZones = false,
		disabled = false
	}: {
		annotated?: boolean;
		zones?: boolean;
		showAnnotations?: boolean;
		showZones?: boolean;
		disabled?: boolean;
	} = $props();
</script>

<!-- Toggles over a camera picture, in its dark subtree: a scrim when off,
     the primary when on. The caller places them (MediaTile's overlay). -->
{#snippet toggle(Icon: typeof SendToBack, active: boolean, label: string, onToggle: () => void)}
	<button
		type="button"
		{disabled}
		onclick={onToggle}
		title={label}
		aria-pressed={active}
		aria-label={label}
		class="inline-flex size-(--size-control-sm) items-center justify-center rounded-button transition-colors disabled:pointer-events-none disabled:opacity-45 {active
			? 'bg-primary text-on-primary hover:bg-primary-hover'
			: 'bg-scrim text-ink-muted hover:text-ink'}"
	>
		<Icon size={14} />
	</button>
{/snippet}

{#if showAnnotations || showZones}
	<div class="flex gap-1">
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
	</div>
{/if}
