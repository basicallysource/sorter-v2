<script lang="ts">
	import StorageLayerSettingsSection from '$lib/components/settings/StorageLayerSettingsSection.svelte';
</script>

<div class="flex flex-col gap-4">
	<header>
		<h1 class="text-xl font-semibold text-text">Storage Layers</h1>
		<p class="mt-1 text-sm text-text-muted">
			Set the layer layout, assign servos per layer, and test or calibrate them.
		</p>
	</header>

	<StorageLayerSettingsSection />
</div>
