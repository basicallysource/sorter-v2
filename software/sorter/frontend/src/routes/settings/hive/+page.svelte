<script lang="ts">
	import HiveSection from '$lib/components/settings/HiveSection.svelte';
	import HiveModelsSection from '$lib/components/settings/HiveModelsSection.svelte';
	import HiveRuntimesSection from '$lib/components/settings/HiveRuntimesSection.svelte';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
</script>

<div class="flex flex-col gap-6">
	<SectionCard
		title="Hive"
		description="Connect this sorter to Hive for registration, uploads, and backfill of archived samples."
	>
		<HiveSection />
	</SectionCard>

	<SectionCard
		title="Model Compatibility"
		description="For each shipping model format, which backends can this machine run — and how fast they're expected to be."
	>
		<HiveRuntimesSection />
	</SectionCard>

	<SectionCard
		title="Models"
		description="Browse and download detection models published to a connected Hive."
	>
		<HiveModelsSection />
	</SectionCard>
</div>
