<script lang="ts">
	import ColorPicker from '$lib/components/ui/ColorPicker.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import { getCurrentThemeColorId, setThemeColor } from '$lib/stores/themeColor.svelte';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	// Every step takes these; the color is the browser's and the machine's own.
	let {}: { flow: SetupFlow; onnext: () => void } = $props();

	let colorId = $state(getCurrentThemeColorId());
</script>

<Panel>
	<ColorPicker bind:value={colorId} onchange={(id) => void setThemeColor(id)} />
</Panel>
