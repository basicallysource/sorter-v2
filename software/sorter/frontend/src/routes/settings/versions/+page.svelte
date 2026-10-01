<script lang="ts">
	import VersionsSection from '$lib/components/settings/VersionsSection.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
</script>

<svelte:head><title>Sorter - Versions</title></svelte:head>

<PageHeader
	title="Versions"
	description="Which version of the software this machine runs, and updating it with one click."
/>
<VersionsSection />
