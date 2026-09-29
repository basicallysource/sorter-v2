<script lang="ts">
	import HiveSection from '$lib/components/settings/HiveSection.svelte';
	import PageTitle from '$lib/components/settings/PageTitle.svelte';
</script>

<svelte:head><title>Sorter - Hive</title></svelte:head>

<PageTitle
	title="Hive"
	description="Connect this sorter to a Hive: pair it, choose what it uploads, and backfill archived samples."
/>
<HiveSection />
