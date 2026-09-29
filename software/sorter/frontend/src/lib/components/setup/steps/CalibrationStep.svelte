<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount } from 'svelte';

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
		if (error) return 'border-danger bg-primary-soft text-[#7A0A0B]';
		if (triggered) return 'border-success bg-[#D4EDDA] text-success-ink';
		return 'border-line bg-well text-ink-muted';
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

<div class="flex flex-col gap-4">
	{#if systemState === 'initializing' || systemState === 'homing'}
		<div
			class="flex items-center gap-3 border border-warning bg-[#FFF7E0] px-4 py-3 text-sm text-[#7A5A00]"
		>
			<div class="flex flex-col">
				<span class="font-medium">Powering on steppers…</span>
				<span class="text-xs text-[#7A5A00]/80">
					{homingStep ?? 'Discovering hardware'} — endstop checks unlock once the boards are
					ready.
				</span>
			</div>
		</div>
	{:else if systemState === 'standby'}
		<div class="setup-panel flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
			<span class="text-ink-muted">The steppers are off.</span>
			<button
				onclick={onInitialize}
				class="setup-button-secondary inline-flex items-center gap-2 px-3 py-1.5 text-sm text-ink transition-colors"
			>
				Power on steppers
			</button>
		</div>
	{:else if systemState === 'error'}
		<div
			class="flex items-center gap-3 border border-danger bg-primary-soft px-4 py-3 text-sm text-[#7A0A0B]"
		>
			<div class="flex flex-col">
				<span class="font-medium">Hardware connection failed</span>
				<span class="text-xs text-[#7A0A0B]/80">
					{homingStep ?? 'The steppers could not be initialized — check the USB cabling and reset the wizard.'}
				</span>
			</div>
		</div>
	{/if}

	<div class="setup-panel px-4 py-3 text-sm text-ink-muted">
		<div class="flex flex-wrap items-start justify-between gap-3">
			<div class="min-w-0 flex-1">
				Verify the chute endstop before homing.
			</div>
			<button
				onclick={() => (showEndstopWiringHelp = !showEndstopWiringHelp)}
				class="setup-button-secondary inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-ink transition-colors"
			>
				{showEndstopWiringHelp ? 'Hide wiring help' : 'Show wiring help'}
			</button>
		</div>
	</div>

	{#if showEndstopWiringHelp}
		<div class="setup-panel px-4 py-4 text-sm text-ink">
			<div class="text-sm font-semibold text-ink">SKR Pico endstop wiring</div>
			<div class="mt-1 text-sm text-ink-muted">
				Reference for the SKR Pico V1.0 endstop header used by the distributor board.
			</div>
			<div class="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
				<a
					href={SKR_PICO_WIRING_DIAGRAM_URL}
					target="_blank"
					rel="noopener noreferrer"
					class="block border border-line bg-white p-1"
				>
					<img
						src={SKR_PICO_WIRING_DIAGRAM_URL}
						alt="SKR Pico V1.0 board with labeled headers"
						loading="lazy"
						class="block h-auto w-full"
					/>
				</a>
				<div class="flex flex-col gap-2 text-xs">
					<div class="font-semibold text-ink">Sorter mapping</div>
					<table class="w-full border-collapse">
						<tbody>
							<tr>
								<td class="py-1 pr-3 text-ink-muted">Chute endstop</td>
								<td class="py-1 font-medium text-ink">Distributor · E0-STOP</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</div>
	{/if}

	<div class="grid gap-4">
		<div class="setup-panel p-4">
			<div class="flex items-start justify-between gap-3">
				<div>
					<div class="text-sm font-semibold text-ink">Chute endstop and home</div>
					<div class="mt-1 text-sm text-ink-muted">
						Set the chute homing polarity and verify the chute can find its mechanical reference.
					</div>
				</div>
			</div>

			<div class="mt-4 text-sm text-ink-muted">
				<span class="font-medium text-ink">Step 1:</span> Manually trigger the chute endstop and
				confirm the indicator below flips to <span class="font-medium text-ink">Triggered</span>.
				Adjust the polarity below if it stays Not triggered.
			</div>

			<div
				class={`mt-3 flex items-center justify-between border px-4 py-3 transition-colors ${endstopStatusClass(
					chuteLive.endstop_triggered,
					chuteLive.endstop_error
				)}`}
			>
				<span class="text-xs">Chute endstop</span>
				<span class="text-base font-semibold">
					{endstopStatusLabel(
						chuteLive.endstop_triggered,
						chuteLive.endstop_error,
						chuteLive.live_available
					)}
				</span>
			</div>
			<div class="mt-2 text-sm text-ink-muted">
				Input channel
				<span class="font-medium text-ink"> {chuteLive.home_pin_channel ?? '--'}</span>
				{#if chuteLive.raw_endstop_high !== null}
					· raw signal
					<span class="font-medium text-ink">
						{chuteLive.raw_endstop_high ? 'HIGH' : 'LOW'}
					</span>
				{/if}
			</div>
			{#if chuteLive.endstop_error}
				<div class="mt-2 border border-danger bg-primary-soft px-3 py-2 text-sm text-[#7A0A0B]">
					Live endstop read failed: {chuteLive.endstop_error}
				</div>
			{/if}

			<div class="mt-4 grid gap-3 sm:grid-cols-2">
				<label class="flex flex-col gap-1 text-sm">
					<span class="text-ink-muted">First bin center</span>
					<input
						type="number"
						step="0.1"
						bind:value={chuteFirstBinCenter}
						class="setup-control px-3 py-2 text-ink"
					/>
				</label>
				<label class="flex flex-col gap-1 text-sm">
					<span class="text-ink-muted">Pillar width (deg)</span>
					<input
						type="number"
						step="0.1"
						bind:value={chutePillarWidthDeg}
						class="setup-control px-3 py-2 text-ink"
					/>
				</label>
			</div>

			<div class="mt-3 flex flex-col gap-2">
				<div>
					<button
						onclick={flipChutePolarity}
						disabled={chuteSaving}
						class="setup-button-secondary inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-ink transition-colors disabled:cursor-not-allowed disabled:opacity-60"
					>
						{chuteSaving ? 'Saving…' : 'Trigger state looks inverted? Flip polarity'}
					</button>
					<div class="mt-1 text-sm text-ink-muted">
						Currently treating the input as
						<span class="font-medium text-ink"
							>{chuteEndstopActiveHigh ? 'active-high' : 'active-low'}</span
						>.
					</div>
				</div>
				<div>
					<button
						onclick={flipChuteDirection}
						disabled={chuteSaving}
						class="setup-button-secondary inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-ink transition-colors disabled:cursor-not-allowed disabled:opacity-60"
					>
						{chuteSaving ? 'Saving…' : 'Chute moves the wrong way? Flip direction'}
					</button>
					<div class="mt-1 text-sm text-ink-muted">
						Stepper direction is currently
						<span class="font-medium text-ink">
							{chuteLive.stepper_direction_inverted === null
								? '--'
								: chuteLive.stepper_direction_inverted
									? 'inverted'
									: 'normal'}
						</span>.
					</div>
				</div>
			</div>

			<div class="mt-1 text-sm text-ink-muted">
				First-bin and pillar values are saved automatically when you continue to the next step.
			</div>

			<div class="mt-4 flex flex-wrap gap-2">
				<button
					onclick={findChuteEndstop}
					disabled={!(systemState === 'ready' || systemState === 'initialized') || chuteHoming}
					class="border border-success bg-success px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-60"
				>
					{chuteHoming ? 'Homing...' : 'Find chute endstop'}
				</button>
				<button
					onclick={cancelChute}
					disabled={chuteCanceling}
					class="setup-button-secondary px-3 py-2 text-sm text-ink transition-colors disabled:cursor-not-allowed disabled:opacity-60"
				>
					{chuteCanceling ? 'Stopping...' : 'Stop motion'}
				</button>
			</div>

			{#if chuteError}
				<div
					class="mt-3 border border-danger bg-primary-soft px-3 py-2 text-sm text-[#7A0A0B]"
				>
					{chuteError}
				</div>
			{:else if chuteStatus}
				<div
					class="mt-3 border border-success bg-[#D4EDDA] px-3 py-2 text-sm font-medium text-success-ink"
				>
					{chuteStatus}
				</div>
			{/if}
		</div>
	</div>
</div>
