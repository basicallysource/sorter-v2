<script lang="ts">
	import ServoLayerCalibrator from '$lib/components/servo/ServoLayerCalibrator.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
</script>

<svelte:head><title>Sorter - Storage layers</title></svelte:head>

<PageHeader
	title="Storage layers"
	description="Each layer's servo: its channel, its open and closed angles, and its bins."
/>
<ServoLayerCalibrator />
