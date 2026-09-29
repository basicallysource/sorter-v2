<script lang="ts">
	import IncidentHandlingSection from '$lib/components/settings/IncidentHandlingSection.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
</script>

<svelte:head><title>Sorter - Incidents</title></svelte:head>

<PageHeader
	title="Incidents"
	description="What the machine does when something goes wrong mid-sort: ignore it, wait for someone, or recover by itself where it can."
/>

<Panel flush>
	<IncidentHandlingSection />
</Panel>
