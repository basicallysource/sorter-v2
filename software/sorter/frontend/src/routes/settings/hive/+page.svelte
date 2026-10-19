<script lang="ts">
	import HiveSection from '$lib/components/settings/HiveSection.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
</script>

<svelte:head><title>Sorter - Hive</title></svelte:head>

<PageHeader
	title="Hive"
	description="Pair this sorter with a Hive, and choose which ones it sends samples to. What each one receives is set in Data."
/>
<HiveSection />
