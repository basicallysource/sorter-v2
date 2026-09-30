<script lang="ts">
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import GeneralSection from '$lib/components/settings/GeneralSection.svelte';
	import ApiKeysSection from '$lib/components/settings/ApiKeysSection.svelte';
	import SampleCaptureSection from '$lib/components/settings/SampleCaptureSection.svelte';
	import SampleStorageSection from '$lib/components/settings/SampleStorageSection.svelte';
	import TailscaleSection from '$lib/components/settings/TailscaleSection.svelte';
	import WifiSection from '$lib/components/settings/WifiSection.svelte';
</script>

<svelte:head><title>Sorter - Settings</title></svelte:head>

<PageHeader title="General" description="This machine, how this page reaches it, and how it looks." />

<GeneralSection />

<Panel title="Wi-Fi" description="Scan for and join wireless networks, on any of the machine's adapters.">
	<WifiSection />
</Panel>

<Panel title="Tailscale" description="The machine's Tailscale connection: join a network or switch to another.">
	<TailscaleSection />
</Panel>

<Panel title="OpenRouter" description="The key used for cloud-assisted detection.">
	<ApiKeysSection />
</Panel>

<Panel
	title="Sample capture"
	description="Camera frames collected for training. Runs in any machine mode and changes nothing about sorting."
	flush
>
	<SampleCaptureSection />
</Panel>

<Panel title="Local samples" description="The sample sessions stored on this machine." flush>
	<SampleStorageSection />
</Panel>
