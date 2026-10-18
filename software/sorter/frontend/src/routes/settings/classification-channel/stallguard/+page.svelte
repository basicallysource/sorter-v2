<script lang="ts">
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import StepperStallGuard from '$lib/components/settings/StepperStallGuard.svelte';
</script>

<svelte:head><title>Sorter - Classification channel StallGuard</title></svelte:head>

<PageHeader
	title="Classification channel StallGuard"
	description="Stop the machine when the classification channel's stepper stalls. Follow the steps to tune how sensitive it is."
/>
<StepperStallGuard motor="carousel" label="the classification channel stepper" />
