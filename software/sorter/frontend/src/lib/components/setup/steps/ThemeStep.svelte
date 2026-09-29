<script lang="ts">
	import ColorPicker from '$lib/components/ui/ColorPicker.svelte';
	import { getCurrentThemeColorId, setThemeColor } from '$lib/stores/themeColor.svelte';

	let colorId = $state(getCurrentThemeColorId());
</script>

<div class="flex flex-col gap-4">
	<p class="text-sm text-ink-muted">
		Pick the LEGO color you want across the UI. Buttons, focus rings and the current page change at
		once.
	</p>
	<div class="rounded-control bg-well p-4">
		<ColorPicker bind:value={colorId} onchange={(id) => void setThemeColor(id)} />
	</div>
</div>
