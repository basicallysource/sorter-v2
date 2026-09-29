<script lang="ts">
	import House from '@lucide/svelte/icons/house';
	import OctagonAlert from '@lucide/svelte/icons/octagon-alert';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import Wordmark from '$lib/components/Wordmark.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';

	let faultOpen = $state(false);
	let homing = $state(false);

	function homeAgain() {
		homing = true;
		setTimeout(() => {
			homing = false;
			faultOpen = false;
		}, 1400);
	}
</script>

<svelte:head><title>Notices · Sorter design system</title></svelte:head>

<PageHeader
	title="Notices"
	lead="One shape for every message in the flow of a page, in four tones. The tone says how much it matters; the shape never changes."
	doc="components"
/>

<SiteSection
	title="Four tones"
	lead="A tint of the tone, its icon, a title and a sentence. No border, and never a stripe down one side."
>
	<Specimen
		code={`<Alert tone="warning" title="Calibration is weak">
	The reference patches drifted by 8.3. Shoot the card again.
</Alert>`}
	>
		<div class="flex flex-col gap-3">
			<Alert tone="info" title="Hold the card under the camera">
				Place the reference card flat on the channel, then press Capture.
			</Alert>
			<Alert tone="success" title="Connected to Hive"
				>Samples upload as the machine saves them.</Alert
			>
			<Alert tone="warning" title="Calibration is weak">
				The reference patches drifted by 8.3. Shoot the card again.
			</Alert>
			<Alert tone="danger" title="Could not reach Hive">
				Check the address and the machine's internet connection.
			</Alert>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="Shorter and with actions"
	lead="A notice can be one sentence, and can carry the action that resolves it."
>
	<Specimen>
		<div class="flex flex-col gap-3">
			<Alert tone="info">This machine has never been homed since it started.</Alert>
			<Alert tone="warning" title="Unsaved changes">
				Two settings differ from what the machine is running.
				{#snippet actions()}
					<Button size="sm" variant="ghost">Discard</Button>
					<Button size="sm" variant="primary">Save</Button>
				{/snippet}
			</Alert>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="A hardware fault"
	lead="When the machine stops for a hardware reason, a banner sits under the top bar on every page, and its Details open the whole message and the way back. The top bar owns the line between them, so the banner is only a fill."
>
	<div class="rounded-panel bg-surface p-2">
		<div class="overflow-hidden rounded-control bg-canvas">
			<TopBar items={[{ href: '/notices', label: 'Dashboard' }]} sticky={false}>
				{#snippet brand()}<Wordmark href="/notices" />{/snippet}
			</TopBar>
			<div class="flex flex-wrap items-center gap-x-4 gap-y-2 bg-danger-soft px-4 py-2.5 sm:px-6">
				<OctagonAlert size={18} class="shrink-0 text-danger-ink" />
				<p class="min-w-0 flex-1 text-sm text-ink">
					<span class="font-semibold">Stepper setup failed.</span>
					The control board could not configure the C-Channel 2 stepper.
				</p>
				<Button size="sm" onclick={() => (faultOpen = true)}>Details</Button>
			</div>
			<div class="p-4 sm:p-6">
				<div class="h-24 bg-surface"></div>
			</div>
		</div>
	</div>
</SiteSection>

<SiteSection
	title="An error in a field"
	lead="An error that belongs to one field is the sentence under it, in danger ink, and the field's edge. It is not a notice."
>
	<Specimen>
		<div class="max-w-sm">
			<Field
				label="Floor rate"
				for="n-floor"
				error="The floor has to be lower than the burst rate."
			>
				<Input id="n-floor" type="number" value={12} unit="/hr" invalid />
			</Field>
		</div>
	</Specimen>
</SiteSection>

<SiteSection title="Where a notice goes">
	<ul class="divide-y divide-line overflow-hidden rounded-panel bg-surface text-sm">
		<li class="px-5 py-3">
			<span class="font-medium text-ink">In the flow, next to what it is about:</span>
			<span class="text-ink-muted"
				>at the top of the panel whose save failed, above the list that is empty for a reason.</span
			>
		</li>
		<li class="px-5 py-3">
			<span class="font-medium text-ink">Under the top bar</span>
			<span class="text-ink-muted"
				>only for what stops the whole machine, like the fault above.</span
			>
		</li>
		<li class="px-5 py-3">
			<span class="font-medium text-ink">Never floating, never on a timer.</span>
			<span class="text-ink-muted">A notice stays until what it says stops being true.</span>
		</li>
		<li class="px-5 py-3">
			<span class="font-medium text-ink">A fifth kind of message is a panel,</span>
			<span class="text-ink-muted">not a new notice shape.</span>
		</li>
	</ul>
</SiteSection>

<Modal bind:open={faultOpen} title="Stepper setup failed">
	<div class="flex flex-col gap-3">
		<p class="text-ink">
			The control board could not configure the C-Channel 2 stepper (4 tries: no answer from the
			driver).
		</p>
		<p class="text-ink-muted">
			Check that the machine has power and that the stepper's cable is seated, then home again.
		</p>
	</div>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (faultOpen = false)}>Close</Button>
		<Button variant="primary" icon={House} loading={homing} onclick={homeAgain}>Home again</Button>
	{/snippet}
</Modal>
