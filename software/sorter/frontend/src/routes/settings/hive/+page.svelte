<script lang="ts">
	import HiveSection from '$lib/components/settings/HiveSection.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
</script>

<svelte:head><title>Sorter - Hive</title></svelte:head>

<PageHeader
	title="Hive"
	description="Connect this sorter to a Hive: pair it, choose what it uploads, and backfill archived samples."
/>
<HiveSection />
