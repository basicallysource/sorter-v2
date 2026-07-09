<script lang="ts">
import GeneralSection from '$lib/components/settings/GeneralSection.svelte';
import ApiKeysSection from '$lib/components/settings/ApiKeysSection.svelte';
import SampleCaptureSection from '$lib/components/settings/SampleCaptureSection.svelte';
import SampleStorageSection from '$lib/components/settings/SampleStorageSection.svelte';
import TailscaleSection from '$lib/components/settings/TailscaleSection.svelte';
import WifiSection from '$lib/components/settings/WifiSection.svelte';
import SectionCard from '$lib/components/settings/SectionCard.svelte';
import LegoColorPicker from '$lib/components/LegoColorPicker.svelte';
</script>

<svelte:head><title>Sorter - Settings</title></svelte:head>

<div class="flex flex-col gap-6">
	<SectionCard
		title="Connection & Appearance"
		description="Connect to a machine, manage existing sessions, and set the UI theme."
	>
		<GeneralSection />

		<div class="mt-6 border border-border bg-bg px-5 py-5">
			<div class="text-base font-semibold text-text">Theme color</div>
			<div class="mt-2 max-w-3xl text-sm text-text-muted">
				Pick the LEGO color that drives the rest of the UI — buttons, focus
				rings, and active highlights all switch instantly.
			</div>
			<div class="mt-4">
				<LegoColorPicker />
			</div>
		</div>

		<div class="mt-6 border border-border bg-bg px-5 py-5">
			<div class="text-base font-semibold text-text">Setup Wizard</div>
			<div class="mt-2 max-w-3xl text-sm text-text-muted">
				Need to revisit the guided machine setup? You can still open the Setup Wizard directly to
				walk through hardware setup, cameras, and the initial machine configuration again.
			</div>
			<div class="mt-4">
				<a
					href="/setup"
					class="inline-flex items-center border border-primary bg-primary px-4 py-2 text-sm font-medium text-primary-contrast transition-colors hover:bg-primary-hover"
				>
					Open Setup Wizard
				</a>
			</div>
		</div>
	</SectionCard>

	<SectionCard
		title="WiFi"
		description="Scan and connect to wireless networks. Supports multiple adapters."
	>
		<WifiSection />
	</SectionCard>

	<SectionCard
		title="Tailscale"
		description="View connection status and join or switch Tailscale networks."
	>
		<TailscaleSection />
	</SectionCard>

	<SectionCard
		title="OpenRouter"
		description="Configure the OpenRouter key used for cloud-assisted detection."
	>
		<ApiKeysSection />
	</SectionCard>

	<SectionCard
		title="Sample Capture"
		description="Collect raw camera frames for model training. Runs in any machine mode without changing sorting behavior."
	>
		<SampleCaptureSection />
	</SectionCard>

	<SectionCard
		title="Local Samples"
		description="Browse and manage classification sample sessions stored on this machine."
	>
		<SampleStorageSection />
	</SectionCard>
</div>
