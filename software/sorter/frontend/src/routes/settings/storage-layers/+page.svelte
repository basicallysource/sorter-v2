<script lang="ts">
	import ServoLayerCalibrator from '$lib/components/servo/ServoLayerCalibrator.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
</script>

<svelte:head><title>Sorter - Storage layers</title></svelte:head>

<PageHeader
	title="Storage layers"
	description="Each layer's flap, where it opens and closes, and its bins."
/>
<ServoLayerCalibrator />
