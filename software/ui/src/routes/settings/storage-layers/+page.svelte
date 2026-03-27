<script lang="ts">
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import ServoSettingsSection from '$lib/components/settings/ServoSettingsSection.svelte';
	import StorageLayerSettingsSection from '$lib/components/settings/StorageLayerSettingsSection.svelte';
</script>

<div class="flex flex-col gap-6">
	<SectionCard
		title="Layer Layout"
		description="Set how many bins each storage layer exposes around the chute."
	>
		<StorageLayerSettingsSection />
	</SectionCard>

	<SectionCard
		title="Servo Backend"
		description="Choose the storage-layer servo backend and configure PCA9685 presets or Waveshare bus channels."
	>
		<ServoSettingsSection />
	</SectionCard>
</div>
