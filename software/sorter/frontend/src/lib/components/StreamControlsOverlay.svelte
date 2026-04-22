<script lang="ts">
	import { Crop, Expand, Eye, Layers, Palette, SendToBack, Shapes } from 'lucide-svelte';

	let {
		annotated = $bindable(true),
		colorCorrect = $bindable(true),
		cropped = $bindable(false),
		zones = $bindable(true),
		ghosts = $bindable(false),
		shadow = $bindable(false),
		fullscreen = $bindable(false),
		showAnnotations = true,
		showColor = false,
		showCrop = false,
		showZones = false,
		showGhosts = false,
		showShadow = false,
		showFullscreen = false,
		disabled = false
	}: {
		annotated?: boolean;
		colorCorrect?: boolean;
		cropped?: boolean;
		zones?: boolean;
		ghosts?: boolean;
		shadow?: boolean;
		fullscreen?: boolean;
		showAnnotations?: boolean;
		showColor?: boolean;
		showCrop?: boolean;
		showZones?: boolean;
		showGhosts?: boolean;
		showShadow?: boolean;
		showFullscreen?: boolean;
		disabled?: boolean;
	} = $props();

	const hasAny = $derived(
		showAnnotations || showColor || showCrop || showZones || showGhosts || showShadow || showFullscreen
	);
</script>

{#snippet togglePill(
	Icon: typeof SendToBack,
	active: boolean,
	label: string,
	onToggle: () => void
)}
	<button
		type="button"
		{disabled}
		onclick={onToggle}
		title={label}
		aria-pressed={active}
		aria-label={label}
		class={`pointer-events-auto inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-white shadow-md backdrop-blur-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
			active
				? 'border-primary/70 bg-primary/80 hover:bg-primary'
				: 'border-white/20 bg-black/55 hover:bg-black/70'
		}`}
	>
		<Icon size={13} />
		<span
			class={`h-1.5 w-1.5 rounded-full transition-colors ${
				active ? 'bg-white' : 'bg-white/30'
			}`}
			aria-hidden="true"
		></span>
	</button>
{/snippet}

{#if hasAny}
	<div class="pointer-events-none absolute right-2 top-2 z-10 flex gap-1">
		{#if showAnnotations}
			{@render togglePill(
				SendToBack,
				annotated,
				annotated ? 'Hide annotations' : 'Show annotations',
				() => (annotated = !annotated)
			)}
		{/if}

		{#if showZones}
			{@render togglePill(
				Shapes,
				zones,
				zones ? 'Hide zones' : 'Show zones',
				() => (zones = !zones)
			)}
		{/if}

		{#if showGhosts}
			{@render togglePill(
				Eye,
				ghosts,
				ghosts ? 'Hide ghosts' : 'Show ghosts',
				() => (ghosts = !ghosts)
			)}
		{/if}

		{#if showShadow}
			{@render togglePill(
				Layers,
				shadow,
				shadow ? 'Hide rt shadow overlay' : 'Show rt shadow overlay',
				() => (shadow = !shadow)
			)}
		{/if}

		{#if showColor}
			{@render togglePill(
				Palette,
				colorCorrect,
				colorCorrect ? 'Disable color correction' : 'Enable color correction',
				() => (colorCorrect = !colorCorrect)
			)}
		{/if}

		{#if showCrop}
			{@render togglePill(
				Crop,
				cropped,
				cropped ? 'Show full frame' : 'Show cropped view',
				() => (cropped = !cropped)
			)}
		{/if}

		{#if showFullscreen}
			{@render togglePill(
				Expand,
				fullscreen,
				fullscreen ? 'Exit fullscreen' : 'Enter fullscreen',
				() => (fullscreen = !fullscreen)
			)}
		{/if}
	</div>
{/if}
