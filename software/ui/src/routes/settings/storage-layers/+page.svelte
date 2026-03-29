<script lang="ts">
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import StorageLayerSettingsSection from '$lib/components/settings/StorageLayerSettingsSection.svelte';
</script>

<div class="flex flex-col gap-6">
	<SectionCard
		title="Storage Layers"
		description="Set the layer layout, assign servos per layer, and test or calibrate them."
	>
		<StorageLayerSettingsSection />
	</SectionCard>
</div>
