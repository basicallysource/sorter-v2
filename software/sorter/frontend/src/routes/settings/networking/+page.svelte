<script lang="ts">
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import ConnectionSection from '$lib/components/settings/ConnectionSection.svelte';
	import TailscaleSection from '$lib/components/settings/TailscaleSection.svelte';
	import WifiSection from '$lib/components/settings/WifiSection.svelte';
</script>

<svelte:head><title>Sorter - Networking</title></svelte:head>

<PageHeader title="Networking" description="How this page reaches the machine, and the machine's own networks." />

<ConnectionSection />

<Panel title="Wi-Fi" description="Scan for and join wireless networks, on any of the machine's adapters.">
	<WifiSection />
</Panel>

<Panel title="Tailscale" description="The machine's Tailscale connection: join a network or switch to another.">
	<TailscaleSection />
</Panel>
