<script lang="ts">
	import AppHeader from '$lib/components/AppHeader.svelte';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import WiredSection from '$lib/components/network/WiredSection.svelte';
	import WifiSection from '$lib/components/network/WifiSection.svelte';
</script>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="p-4 sm:p-6">
		<div class="mb-4">
			<h2 class="text-xl font-bold text-text">Network</h2>
			<p class="mt-1 text-sm text-text-muted">
				Wired and wireless connectivity of this machine.
			</p>
		</div>

		<div class="flex max-w-3xl flex-col gap-6">
			<SectionCard
				title="Wired"
				description="Ethernet adapters and their current addresses."
			>
				<WiredSection />
			</SectionCard>

			<SectionCard
				title="WiFi"
				description="Scan for wireless networks and connect — the wired connection stays untouched."
			>
				<WifiSection />
			</SectionCard>
		</div>
	</div>
</div>
