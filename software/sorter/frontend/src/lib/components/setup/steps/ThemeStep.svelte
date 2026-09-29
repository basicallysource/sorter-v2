<script lang="ts">
	import ColorPicker from '$lib/components/ui/ColorPicker.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import { getCurrentThemeColorId, setThemeColor } from '$lib/stores/themeColor.svelte';

	let colorId = $state(getCurrentThemeColorId());
</script>

<Panel
	title="Color"
	description="The LEGO color used across the UI. Buttons, focus and the current page change at once."
>
	<ColorPicker bind:value={colorId} onchange={(id) => void setThemeColor(id)} />
</Panel>
