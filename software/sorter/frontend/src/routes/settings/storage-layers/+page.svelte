<script lang="ts">
	import ServoLayerCalibrator from '$lib/components/servo/ServoLayerCalibrator.svelte';
	import PageTitle from '$lib/components/settings/PageTitle.svelte';
</script>

<svelte:head><title>Sorter - Storage layers</title></svelte:head>

<PageTitle
	title="Storage layers"
	description="Each layer's servo: its channel, its open and closed angles, and its bins."
/>
<ServoLayerCalibrator />
