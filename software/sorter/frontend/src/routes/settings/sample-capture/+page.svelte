<script lang="ts">
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SampleCaptureSection from '$lib/components/settings/SampleCaptureSection.svelte';
	import SampleStorageSection from '$lib/components/settings/SampleStorageSection.svelte';
</script>

<svelte:head><title>Sorter - Sample capture</title></svelte:head>

<PageHeader
	title="Sample capture"
	description="Camera frames taken for training while the machine sorts, uploaded to Hive in the background. Changes nothing about sorting."
/>

<Panel title="Capture" flush>
	<SampleCaptureSection />
</Panel>

<Panel title="Local samples" description="The training samples stored on this machine until Hive has them." flush>
	<SampleStorageSection />
</Panel>
