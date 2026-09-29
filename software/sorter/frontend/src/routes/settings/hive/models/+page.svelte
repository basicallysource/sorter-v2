<script lang="ts">
	import HiveModelsSection from '$lib/components/settings/HiveModelsSection.svelte';
	import HiveRuntimesSection from '$lib/components/settings/HiveRuntimesSection.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
</script>

<svelte:head><title>Sorter - Local models</title></svelte:head>

<PageHeader
	title="Local models"
	description="Which neural-network model the sorter uses for live detection. A new machine downloads Hive's default model for its hardware and uses it on every channel until you choose another one here."
/>

<HiveModelsSection />

<Panel
	title="Compatibility and speed"
	description="For each model format, which inference backends this machine can run, and how fast they should be on the chosen model."
>
	<HiveRuntimesSection />
</Panel>
