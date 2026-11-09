<script lang="ts">
	import Pencil from '@lucide/svelte/icons/pencil';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import MeasureTurn from '$lib/components/setup/MeasureTurn.svelte';
	import StepperPanel from '$lib/components/settings/StepperPanel.svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getChute, type ChuteSettings } from '$lib/api/chute';
	import { errorMessage } from '$lib/api/http';
	import { chutePictures } from '$lib/chute/pictures';
	import { getMachineContext } from '$lib/machines/context';

	const machine = getMachineContext();
	const base = $derived(machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase());
	const hardwareState = $derived(machine.machine?.systemStatus?.hardware_state ?? 'standby');

	let chute = $state<ChuteSettings | null>(null);
	let error = $state<string | null>(null);
	let pictureFailed = $state(false);

	async function load() {
		error = null;
		try {
			chute = await getChute(base);
		} catch (e) {
			error = errorMessage(e, 'The chute did not load.');
		}
	}

	$effect(() => {
		void load();
	});

	const picture = $derived(chute && !pictureFailed ? (chutePictures(chute.variant)?.closeUp ?? null) : null);
</script>

<svelte:head><title>Sorter - Chute</title></svelte:head>

<PageHeader
	title="Chute"
	description="Which chute this is, move its stepper by hand, home it, and set its driver."
/>

{#if error}
	<Alert tone="danger" title="The chute did not load">
		{error}
		{#snippet actions()}
			<Button size="sm" icon={RotateCcw} onclick={() => void load()}>Try again</Button>
		{/snippet}
	</Alert>
{:else if !chute}
	<Panel>
		<p class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={16} /> Loading the chute</p>
	</Panel>
{:else}
	<Panel title="Kind of chute">
		{#snippet actions()}
			<Button size="sm" variant="ghost" icon={Pencil} href="/setup?step=chute">Change</Button>
		{/snippet}
		<div class="flex flex-col gap-4 sm:flex-row sm:items-center">
			<span class="block aspect-4/3 w-full max-w-56 shrink-0 rounded-control bg-well">
				{#if picture}
					<img
						src={picture}
						alt=""
						loading="lazy"
						onerror={() => (pictureFailed = true)}
						class="block size-full object-contain"
					/>
				{/if}
			</span>
			<div class="min-w-0 text-sm">
				<p class="font-medium text-ink">{chute.variant_label}</p>
				<p class="text-ink-muted">{chute.variants.find((variant) => variant.key === chute?.variant)?.summary}</p>
				<p class="mt-2 text-ink-muted">
					{chute.home_on === 'magnet'
						? 'It homes on a magnet that passes a sensor once a turn.'
						: 'It homes on a switch at one end of its travel.'}
					{chute.falls_through
						? 'Pieces no bin takes fall into the tray under it.'
						: 'Pieces no bin takes go to its discard bin.'}
				</p>
			</div>
		</div>
	</Panel>
	{#if chute.home_on === 'magnet' && chute.turns_freely}
		<MeasureTurn
			{base}
			{chute}
			ready={hardwareState === 'initialized' || hardwareState === 'ready'}
			onmeasured={(settings) => (chute = settings)}
		/>
	{/if}
{/if}

<StepperPanel
	stepperKey="chute"
	label="Chute stepper"
	endstop={{
		configEndpoint: '/api/hardware-config/chute',
		liveEndpoint: '/api/hardware-config/chute/live',
		homeEndpoint: '/api/hardware-config/chute/calibrate/find-endstop',
		homeCancelEndpoint: '/api/hardware-config/chute/calibrate/cancel'
	}}
/>
