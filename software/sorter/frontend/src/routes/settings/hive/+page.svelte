<script lang="ts">
	import HiveSection from '$lib/components/settings/HiveSection.svelte';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
</script>

<svelte:head><title>Sorter - Hive</title></svelte:head>

<div class="flex flex-col gap-6">
	<SectionCard
		title="Hive"
		description="Connect this sorter to Hive for registration, uploads, and backfill of archived samples."
	>
		<HiveSection />
	</SectionCard>
</div>
