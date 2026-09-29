<script lang="ts">
	import VersionsSection from '$lib/components/settings/VersionsSection.svelte';
	import PageTitle from '$lib/components/settings/PageTitle.svelte';
</script>

<svelte:head><title>Sorter - Versions</title></svelte:head>

<PageTitle
	title="Versions"
	description="Which version of the software this machine runs, and updating it with one click."
/>
<VersionsSection />
