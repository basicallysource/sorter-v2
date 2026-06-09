<script lang="ts">
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import WiredSection from '$lib/components/network/WiredSection.svelte';
	import WifiSection from '$lib/components/network/WifiSection.svelte';
</script>

<div class="flex flex-col gap-6">
	<SectionCard title="Wired" description="Ethernet adapters and their current addresses.">
		<WiredSection />
	</SectionCard>

	<SectionCard
		title="WiFi"
		description="Scan for wireless networks and connect — the wired connection stays untouched."
	>
		<WifiSection />
	</SectionCard>
</div>
