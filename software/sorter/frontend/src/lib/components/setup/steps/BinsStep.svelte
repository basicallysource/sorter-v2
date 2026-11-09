<!-- How many layers of bins the machine has and how many bins each holds. -->
<script lang="ts">
	import LayerBins from '$lib/components/layers/LayerBins.svelte';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	let { flow }: { flow: SetupFlow; onnext: () => void } = $props();
</script>

<LayerBins
	base={flow.base}
	fixedBottom={flow.summary!.config.chute.fixed_bottom_door}
	onsaved={() => flow.reload()}
/>
