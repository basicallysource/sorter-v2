<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount } from 'svelte';
	import Cable from '@lucide/svelte/icons/cable';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';

	type ChuteLiveStatus = {
		live_available: boolean;
		endstop_triggered: boolean | null;
		raw_endstop_high: boolean | null;
		endstop_active_high: boolean | null;
		endstop_error?: string;
		stepper_direction_inverted: boolean | null;
		current_angle: number | null;
		stepper_position_degrees: number | null;
		stepper_microsteps: number | null;
		stepper_stopped: boolean | null;
		digital_inputs: Array<{ channel: number; raw_high: boolean }>;
		home_pin_channel: number | null;
	};

	let { onInitialize }: { onInitialize: () => void } = $props();

	const manager = getMachinesContext();

	const SKR_PICO_WIRING_DIAGRAM_URL = '/setup/skr-pico-v1.0-headers.png';

	let showEndstopWiringHelp = $state(false);
	let loadedMachineKey = $state('');
	const systemState = $derived(manager.selectedMachine?.systemStatus?.hardware_state ?? 'standby');
	const homingStep = $derived(manager.selectedMachine?.systemStatus?.homing_step ?? null);
	let chuteLoading = $state(false);
	let chuteSaving = $state(false);
	let chuteHoming = $state(false);
	let chuteCanceling = $state(false);
	let chuteError = $state<string | null>(null);
	let chuteStatus = $state('');
	let chuteFirstBinCenter = $state(8.25);
	let chutePillarWidthDeg = $state(8.25);
	let chuteEndstopActiveHigh = $state(true);
	let chuteLive = $state<ChuteLiveStatus>({
		live_available: false,
		endstop_triggered: null,
		raw_endstop_high: null,
		endstop_active_high: null,
		stepper_direction_inverted: null,
		current_angle: null,
		stepper_position_degrees: null,
		stepper_microsteps: null,
		stepper_stopped: null,
		digital_inputs: [],
		home_pin_channel: null
	});

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	function optionalChannel(value: unknown): number | null {
		return typeof value === 'number' && Number.isInteger(value) ? value : null;
	}

	function endstopStatusLabel(
		triggered: boolean | null,
		error: string | undefined,
		liveAvailable: boolean
	): string {
		if (error) return 'Read error';
		if (!liveAvailable) return 'Offline';
		if (triggered === null) return '--';
		return triggered ? 'Triggered' : 'Not triggered';
	}

	function endstopStatusClass(triggered: boolean | null, error: string | undefined): string {
		if (error) return 'bg-danger-soft text-danger-ink';
		if (triggered) return 'bg-success-soft text-success-ink';
		return 'bg-well text-ink-muted';
	}

	async function loadChuteSettings() {
		chuteLoading = true;
		try {
			const [configRes, liveRes] = await Promise.all([
				fetch(`${currentBackendBaseUrl()}/api/hardware-config/chute`),
				fetch(`${currentBackendBaseUrl()}/api/hardware-config/chute/live`)
			]);
			let configuredHomePinChannel: number | null = null;
			if (configRes.ok) {
				const configPayload = await configRes.json();
				chuteFirstBinCenter = Number(configPayload?.first_bin_center ?? 8.25);
				chutePillarWidthDeg = Number(configPayload?.pillar_width_deg ?? 8.25);
				chuteEndstopActiveHigh = Boolean(configPayload?.endstop_active_high ?? true);
				configuredHomePinChannel = optionalChannel(configPayload?.home_pin_channel);
			}
			if (liveRes.ok) {
				const livePayload = (await liveRes.json()) as ChuteLiveStatus;
				chuteLive = {
					...livePayload,
					home_pin_channel: livePayload.home_pin_channel ?? configuredHomePinChannel
				};
				if (typeof livePayload.endstop_active_high === 'boolean') {
					chuteEndstopActiveHigh = livePayload.endstop_active_high;
				}
			} else {
				chuteLive = { ...chuteLive, home_pin_channel: configuredHomePinChannel };
			}
		} finally {
			chuteLoading = false;
		}
	}

	async function flipChutePolarity() {
		chuteEndstopActiveHigh = !chuteEndstopActiveHigh;
		await saveChuteSettings();
	}

	async function flipChuteDirection() {
		chuteSaving = true;
		chuteError = null;
		chuteStatus = '';
		const current = chuteLive.stepper_direction_inverted ?? false;
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/setup-wizard/stepper-directions/chute`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ inverted: !current })
				}
			);
			if (!res.ok) throw new Error(await res.text());
			chuteStatus = `Chute direction set to ${!current ? 'inverted' : 'normal'}.`;
			await loadChuteSettings();
		} catch (e: any) {
			chuteError = e.message ?? 'Failed to flip chute direction';
		} finally {
			chuteSaving = false;
		}
	}

	async function saveChuteSettings() {
		chuteSaving = true;
		chuteError = null;
		chuteStatus = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/chute`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					first_bin_center: chuteFirstBinCenter,
					pillar_width_deg: chutePillarWidthDeg,
					endstop_active_high: chuteEndstopActiveHigh
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			chuteStatus = payload?.message ?? 'Chute settings saved.';
			await loadChuteSettings();
		} catch (e: any) {
			chuteError = e.message ?? 'Failed to save chute settings';
		} finally {
			chuteSaving = false;
		}
	}

	async function findChuteEndstop() {
		chuteHoming = true;
		chuteError = null;
		chuteStatus = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/chute/calibrate/find-endstop`,
				{ method: 'POST' }
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			chuteStatus = payload?.message ?? 'Chute endstop found.';
			await loadChuteSettings();
		} catch (e: any) {
			chuteError = e.message ?? 'Failed to find chute endstop';
		} finally {
			chuteHoming = false;
		}
	}

	async function cancelChute() {
		chuteCanceling = true;
		chuteError = null;
		chuteStatus = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/chute/calibrate/cancel`,
				{ method: 'POST' }
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			chuteStatus = payload?.message ?? 'Chute motion canceled.';
			await loadChuteSettings();
		} catch (e: any) {
			chuteError = e.message ?? 'Failed to cancel chute motion';
		} finally {
			chuteCanceling = false;
		}
	}

	export async function persistPendingSettings(): Promise<boolean> {
		try {
			await saveChuteSettings();
			return chuteError === null;
		} catch {
			return false;
		}
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ??
			'__local__';
		if (machineKey === loadedMachineKey) return;
		loadedMachineKey = machineKey;
		void loadChuteSettings();
	});

	onMount(() => {
		const interval = setInterval(() => {
			if (systemState === 'ready' || systemState === 'initialized') {
				void loadChuteSettings();
			}
		}, 1200);
		return () => clearInterval(interval);
	});
</script>

<div class="flex flex-col gap-(--gap-panels)">
	{#if systemState === 'initializing' || systemState === 'homing'}
		<Alert tone="warning" title="Powering on the steppers…">
			{homingStep ?? 'Finding the hardware'}. The endstop checks unlock once the boards are ready.
		</Alert>
	{:else if systemState === 'standby'}
		<Alert tone="info" title="The steppers are off.">
			{#snippet actions()}
				<Button size="sm" onclick={onInitialize}>Power on the steppers</Button>
			{/snippet}
		</Alert>
	{:else if systemState === 'error'}
		<Alert tone="danger" title="The hardware connection failed">
			{homingStep ?? 'The steppers could not start. Check the USB cables and reset the wizard.'}
		</Alert>
	{/if}

	<Panel
		title="Chute endstop and home"
		description="Check the chute's endstop before homing: set its polarity, and make sure the chute can find its mechanical reference."
	>
		{#snippet actions()}
			<Button size="sm" variant="ghost" icon={Cable} onclick={() => (showEndstopWiringHelp = !showEndstopWiringHelp)}>
				<span class="max-sm:sr-only">{showEndstopWiringHelp ? 'Hide the wiring' : 'Show the wiring'}</span>
			</Button>
		{/snippet}
		<div class="flex flex-col gap-4">
			{#if showEndstopWiringHelp}
				<div class="grid grid-cols-1 gap-4 rounded-control bg-well p-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
					<a href={SKR_PICO_WIRING_DIAGRAM_URL} target="_blank" rel="noopener noreferrer" class="block">
						<img
							src={SKR_PICO_WIRING_DIAGRAM_URL}
							alt="SKR Pico V1.0 board with labeled headers"
							loading="lazy"
							class="block h-auto w-full rounded-control"
						/>
					</a>
					<div class="flex flex-col gap-2 text-sm">
						<h3 class="font-medium text-ink">SKR Pico endstop wiring</h3>
						<p class="text-ink-muted">The SKR Pico V1.0 endstop header the distributor board uses.</p>
						<p>
							<span class="text-ink-muted">Chute endstop</span>
							<span class="font-mono text-ink">Distributor · E0-STOP</span>
						</p>
					</div>
				</div>
			{/if}

			<p class="text-sm text-ink-muted">
				First, trigger the chute's endstop by hand and check that it reads Triggered below. If it
				stays Not triggered, flip the polarity.
			</p>
			<div
				class="flex items-center justify-between rounded-control px-4 py-3 transition-colors {endstopStatusClass(
					chuteLive.endstop_triggered,
					chuteLive.endstop_error
				)}"
			>
				<span class="text-sm">Chute endstop</span>
				<span class="text-base font-semibold">
					{endstopStatusLabel(chuteLive.endstop_triggered, chuteLive.endstop_error, chuteLive.live_available)}
				</span>
			</div>
			<p class="text-sm text-ink-muted">
				Input channel <span class="font-medium text-ink">{chuteLive.home_pin_channel ?? '–'}</span>
				{#if chuteLive.raw_endstop_high !== null}
					· raw signal <span class="font-medium text-ink">{chuteLive.raw_endstop_high ? 'high' : 'low'}</span>
				{/if}
			</p>
			{#if chuteLive.endstop_error}
				<Alert tone="danger">The live endstop read failed: {chuteLive.endstop_error}</Alert>
			{/if}

			<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
				<Field label="First bin center" for="setup-first-bin" help="Saved when you continue.">
					<Input id="setup-first-bin" type="number" step={0.1} bind:value={chuteFirstBinCenter} />
				</Field>
				<Field label="Pillar width" for="setup-pillar" help="Saved when you continue.">
					<Input id="setup-pillar" type="number" step={0.1} unit="°" bind:value={chutePillarWidthDeg} />
				</Field>
			</div>

			<div class="flex flex-col gap-3 text-sm text-ink-muted">
				<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
					<Button size="sm" loading={chuteSaving} onclick={flipChutePolarity}>Flip the polarity</Button>
					<span>
						If the trigger looks inverted. The input reads as
						<span class="font-medium text-ink">{chuteEndstopActiveHigh ? 'active-high' : 'active-low'}</span>.
					</span>
				</div>
				<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
					<Button size="sm" loading={chuteSaving} onclick={flipChuteDirection}>Flip the direction</Button>
					<span>
						If the chute moves the wrong way. Its direction is
						<span class="font-medium text-ink">
							{chuteLive.stepper_direction_inverted === null
								? '–'
								: chuteLive.stepper_direction_inverted
									? 'inverted'
									: 'normal'}</span
						>.
					</span>
				</div>
			</div>

			{#if chuteError}
				<Alert tone="danger">{chuteError}</Alert>
			{:else if chuteStatus}
				<Alert tone="success">{chuteStatus}</Alert>
			{/if}
		</div>
		{#snippet footer()}
			<Button variant="ghost" loading={chuteCanceling} onclick={cancelChute}>Stop the motion</Button>
			<Button
				variant="primary"
				loading={chuteHoming}
				disabled={!(systemState === 'ready' || systemState === 'initialized')}
				onclick={findChuteEndstop}
			>
				Find the chute endstop
			</Button>
		{/snippet}
	</Panel>
</div>
