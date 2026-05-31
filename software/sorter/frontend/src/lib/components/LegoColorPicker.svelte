<script lang="ts">
	/**
	 * Grid of LEGO color swatches. Picking one immediately re-skins the UI
	 * (CSS-var update on `<html>`) and persists the choice to the backend.
	 *
	 * Used by the setup wizard's "Your Color" step and by Settings.
	 */
	import { LEGO_COLORS } from '$lib/lego-colors';
	import { getCurrentThemeColorId, setThemeColor } from '$lib/stores/themeColor.svelte';
	import { Check } from 'lucide-svelte';

	const selected = $derived(getCurrentThemeColorId());
	let hovered = $state<string | null>(null);

	function handlePick(colorId: string): void {
		void setThemeColor(colorId);
	}

	const displayName = $derived(
		LEGO_COLORS.find((c) => c.id === (hovered ?? selected))?.name ?? '—'
	);
	const isHovering = $derived(hovered !== null && hovered !== selected);
</script>

<div class="grid gap-1" style="grid-template-columns: repeat(auto-fill, minmax(1.5rem, 1fr));">
	{#each LEGO_COLORS as color (color.id)}
		{@const isActive = selected === color.id}
		<button
			type="button"
			title={color.name}
			onclick={() => handlePick(color.id)}
			onmouseenter={() => (hovered = color.id)}
			onmouseleave={() => (hovered = null)}
			aria-pressed={isActive}
			aria-label={color.name}
			class="group relative flex h-6 w-full items-center justify-center transition-transform hover:scale-110"
			style="background-color: {color.hex}; color: {color.contrast === 'white' ? '#ffffff' : '#000000'};"
		>
			{#if isActive}
				<span
					class="absolute inset-0 border-2"
					style="border-color: {color.contrast === 'white' ? '#ffffff' : '#000000'};"
				></span>
				<Check size={14} strokeWidth={3} />
			{/if}
		</button>
	{/each}
</div>

<div class="mt-3 text-xs text-text-muted">
	{isHovering ? '' : 'Picked:'} <span class="font-medium text-text">{displayName}</span>
</div>
