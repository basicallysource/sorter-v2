<script lang="ts">
	import IncidentHandlingSection from '$lib/components/settings/IncidentHandlingSection.svelte';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
</script>

<svelte:head><title>Sorter - Incidents</title></svelte:head>

<SectionCard
	title="Incident Handling"
	description="How the machine responds when something goes wrong mid-sort: ignore the condition, wait for an operator, or recover automatically where supported."
>
	<IncidentHandlingSection />
</SectionCard>
