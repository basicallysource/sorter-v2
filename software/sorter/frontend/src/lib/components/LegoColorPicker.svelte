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

	function handlePick(colorId: string): void {
		void setThemeColor(colorId);
	}
</script>

<div class="grid grid-cols-5 gap-1.5 sm:grid-cols-8 md:grid-cols-10">
	{#each LEGO_COLORS as color (color.id)}
		{@const isActive = selected === color.id}
		<button
			type="button"
			title={color.name}
			onclick={() => handlePick(color.id)}
			aria-pressed={isActive}
			aria-label={color.name}
			class="group relative flex aspect-square flex-col items-center justify-center text-center transition-transform hover:scale-105"
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
	Picked: <span class="font-medium text-text">{LEGO_COLORS.find((c) => c.id === selected)?.name ?? '—'}</span>
</div>
