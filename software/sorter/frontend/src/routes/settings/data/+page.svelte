<script lang="ts">
	import LocalDataPanel from '$lib/components/data/LocalDataPanel.svelte';
	import SharingPanel from '$lib/components/data/SharingPanel.svelte';
	import SampleCaptureSection from '$lib/components/settings/SampleCaptureSection.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
</script>

<svelte:head><title>Sorter - Data</title></svelte:head>

<PageHeader
	title="Data"
	description="What this sorter shares with each Hive, how it captures samples, and what it keeps here."
/>

<SharingPanel />

<Panel
	title="Sample capture"
	description="Camera frames taken while the machine sorts, to train detection. Changes nothing about sorting."
	flush
>
	<SampleCaptureSection />
</Panel>

<LocalDataPanel />
