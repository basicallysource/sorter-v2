<!--
	The chute's home and where its bins are. By what the chute homes on: a
	switch (check it reads pressed when pressed, flip how it reads if not,
	then find it) or a magnet (check the sensor sees the magnet, find home on
	it, then measure one turn). Then the first section's start and the pillar
	between sections. The sensor is read live; what is typed is never
	overwritten by it.
-->
<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import House from '@lucide/svelte/icons/house';
	import Square from '@lucide/svelte/icons/square';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import HardwarePower from '$lib/components/setup/HardwarePower.svelte';
	import MeasureTurn from '$lib/components/setup/MeasureTurn.svelte';
	import { findChuteHome, getChuteLive, saveChute, stopChute, type ChuteLive } from '$lib/api/chute';
	import { errorMessage } from '$lib/api/http';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	let { flow }: { flow: SetupFlow; onnext: () => void } = $props();

	const chute = $derived(flow.summary!.config.chute);
	const magnet = $derived(chute.home_on === 'magnet');
	const homeFound = $derived(flow.marks.chuteHome === chute.variant);

	let live = $state<ChuteLive | null>(null);
	let liveError = $state<string | null>(null);
	let homing = $state(false);
	let stopping = $state(false);
	let flipping = $state(false);
	let homeError = $state<string | null>(null);
	let homeMessage = $state<string | null>(null);

	// The bins' place round the chute, as typed. Loaded once, and again only
	// after a save.
	let offset = $state<number | null>(untrack(() => round(chute.first_section_offset_deg)));
	let pillar = $state<number | null>(untrack(() => round(chute.pillar_width_deg)));
	let savingGeometry = $state(false);
	let geometryError = $state<string | null>(null);
	let geometryMessage = $state<string | null>(null);
	const geometryChanged = $derived(
		offset !== round(chute.first_section_offset_deg) || pillar !== round(chute.pillar_width_deg)
	);
	const pillarInvalid = $derived(pillar === null || !(pillar >= 0 && pillar < chute.section_pitch_deg));

	function round(value: number): number {
		return Math.round(value * 100) / 100;
	}

	async function readLive() {
		try {
			live = await getChuteLive(flow.base);
			liveError = null;
			// Homed by any way (here, the dashboard, a start) counts as having found home.
			if (live.homed && flow.marks.chuteHome !== chute.variant) flow.mark({ chuteHome: chute.variant });
		} catch (e) {
			liveError = errorMessage(e, 'The home sensor could not be read.');
		}
	}

	const reading = $derived.by(() => {
		if (!flow.hardwareUp || !live?.live_available) return { text: 'Motors off', tone: 'off' };
		if (live.endstop_error || liveError) return { text: 'Could not be read', tone: 'danger' };
		if (live.endstop_triggered === null) return { text: 'Unknown', tone: 'off' };
		if (magnet) return live.endstop_triggered ? { text: 'Over the magnet', tone: 'on' } : { text: 'No magnet', tone: 'off' };
		return live.endstop_triggered ? { text: 'Pressed', tone: 'on' } : { text: 'Not pressed', tone: 'off' };
	});

	async function flipPolarity() {
		flipping = true;
		homeError = null;
		try {
			const current = live?.endstop_active_high ?? chute.endstop_active_high;
			await saveChute(flow.base, { endstop_active_high: !current });
			await readLive();
		} catch (e) {
			homeError = errorMessage(e, 'How the sensor reads was not changed.');
		} finally {
			flipping = false;
		}
	}

	async function findHome() {
		homing = true;
		homeError = null;
		homeMessage = null;
		try {
			await findChuteHome(flow.base);
			homeMessage = magnet ? 'The chute found home on its magnet.' : 'The chute found its home switch.';
			flow.mark({ chuteHome: chute.variant });
		} catch (e) {
			homeError = errorMessage(e, 'The chute did not find home.');
		} finally {
			homing = false;
			void readLive();
		}
	}

	async function stop() {
		stopping = true;
		try {
			await stopChute(flow.base);
		} catch (e) {
			homeError = errorMessage(e, 'The chute did not stop.');
		} finally {
			stopping = false;
		}
	}

	async function saveGeometry() {
		if (offset === null || pillarInvalid) {
			geometryError = `The pillar is from 0 to under ${chute.section_pitch_deg.toFixed(1)}°, and the start is a number of degrees.`;
			return;
		}
		savingGeometry = true;
		geometryError = null;
		geometryMessage = null;
		try {
			const result = await saveChute(flow.base, { first_bin_center: offset, pillar_width_deg: pillar! });
			offset = round(result.settings.first_section_offset_deg);
			pillar = round(result.settings.pillar_width_deg);
			geometryMessage = result.message ?? 'Saved.';
			await flow.reload();
		} catch (e) {
			geometryError = errorMessage(e, 'Where the bins are was not saved.');
		} finally {
			savingGeometry = false;
		}
	}

	onMount(() => {
		void readLive();
		const timer = setInterval(() => {
			if (flow.hardwareUp && document.visibilityState === 'visible') void readLive();
		}, 1200);
		return () => clearInterval(timer);
	});
</script>

<div class="flex flex-col gap-(--gap-panels)">
	<HardwarePower {flow} unlocks="The home sensor reads, and the chute can find home, once they are on." />

	<Panel
		title={magnet ? 'Home on the magnet' : 'Home switch'}
		description={magnet
			? 'A magnet on the chute passes a sensor once a turn; that is home. Turn the chute by hand until the magnet is over the sensor and check it reads Over the magnet, then turn it away again.'
			: 'The chute turns to a switch at one end of its travel; that is home. Press the switch by hand and check it reads Pressed.'}
	>
		<div class="flex flex-col gap-4">
			<div
				class="flex items-center justify-between rounded-control px-4 py-3 transition-colors {reading.tone === 'on'
					? 'bg-success-soft text-success-ink'
					: reading.tone === 'danger'
						? 'bg-danger-soft text-danger-ink'
						: 'bg-well text-ink-muted'}"
				aria-live="polite"
			>
				<span class="text-sm">{magnet ? 'Home sensor' : 'Home switch'}</span>
				<span class="text-base font-semibold">{reading.text}</span>
			</div>
			{#if live?.endstop_error}
				<Alert tone="danger">The sensor could not be read: {live.endstop_error}</Alert>
			{/if}
			<div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-muted">
				<Button size="sm" loading={flipping} disabled={!flow.hardwareUp} onclick={() => void flipPolarity()}>
					It reads the other way
				</Button>
				<span>
					{magnet
						? 'If it says Over the magnet when the magnet is away, and No magnet over it.'
						: 'If it says Pressed when it is not, and Not pressed when it is.'}
				</span>
			</div>
			{#if homeError}
				<Alert tone="danger">{homeError}</Alert>
			{:else if homeMessage}
				<Alert tone="success">{homeMessage}</Alert>
			{:else if homeFound}
				<p class="text-sm text-success-ink">The chute has found home here before.</p>
			{/if}
		</div>
		{#snippet footer()}
			{#if homing}
				<Button variant="ghost" icon={Square} loading={stopping} onclick={() => void stop()}>Stop the chute</Button>
			{/if}
			<Button
				variant={homeFound ? 'secondary' : 'primary'}
				icon={House}
				loading={homing}
				disabled={!flow.hardwareUp}
				onclick={() => void findHome()}
			>
				{magnet ? 'Find home on the magnet' : 'Find the home switch'}
			</Button>
		{/snippet}
	</Panel>

	{#if magnet && chute.turns_freely}
		<MeasureTurn base={flow.base} {chute} ready={flow.hardwareUp && !homing} onmeasured={() => void flow.reload()} />
	{/if}

	<Panel
		title="Where the bins are"
		description={chute.turns_freely
			? `The chute has ${chute.num_sections} sections round it, with a pillar between each two. Measure from home to where the first section starts.`
			: `The chute has ${chute.num_sections} sections round it, with a pillar between each two. Measure from home to where the first section starts. It turns up to ${chute.max_angle_deg ?? 0}° from its switch.`}
	>
		<div class="grid max-w-2xl grid-cols-1 gap-4 sm:grid-cols-2">
			<Field label="First section starts at" for="setup-first-section" help="Degrees from home.">
				<Input id="setup-first-section" type="number" step={0.1} unit="°" bind:value={offset} />
			</Field>
			<Field
				label="Pillar between sections"
				for="setup-pillar"
				error={pillarInvalid ? `From 0 to under ${chute.section_pitch_deg.toFixed(1)}°.` : undefined}
				help="Its width, in degrees."
			>
				<Input id="setup-pillar" type="number" step={0.1} unit="°" invalid={pillarInvalid} bind:value={pillar} />
			</Field>
		</div>
		{#if geometryError}
			<Alert tone="danger" class="mt-4">{geometryError}</Alert>
		{/if}
		{#snippet footer()}
			{#if geometryMessage && !geometryChanged}<span class="mr-auto text-sm text-success-ink">{geometryMessage}</span>{/if}
			<Button
				variant="primary"
				loading={savingGeometry}
				disabled={!geometryChanged || pillarInvalid}
				onclick={() => void saveGeometry()}
			>
				Save where the bins are
			</Button>
		{/snippet}
	</Panel>
</div>
