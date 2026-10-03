<script lang="ts">
	import ColorPicker from '$lib/components/ui/ColorPicker.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import { getCurrentThemeColorId, setThemeColor } from '$lib/stores/themeColor.svelte';

	let colorId = $state(getCurrentThemeColorId());
</script>

<Panel>
	<ColorPicker bind:value={colorId} onchange={(id) => void setThemeColor(id)} />
</Panel>
