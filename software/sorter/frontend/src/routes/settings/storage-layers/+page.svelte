<script lang="ts">
	import ServoLayerCalibrator from '$lib/components/servo/ServoLayerCalibrator.svelte';
</script>

<svelte:head>
	<title>Storage Layers · Sorter</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<header>
		<h1 class="text-xl font-semibold text-text">Storage Layers</h1>
		<p class="mt-1 text-sm text-text-muted">
			Configure each layer's servo, calibrate its open/closed angles, and set bin counts.
		</p>
	</header>

	<ServoLayerCalibrator />
</div>
