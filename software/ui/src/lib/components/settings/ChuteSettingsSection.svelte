<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount } from 'svelte';

	const manager = getMachinesContext();

	let loadedMachineKey = $state('');
	let loading = $state(false);
	let saving = $state(false);
	let calibrating = $state(false);
	let canceling = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let firstBinCenter = $state(8.4);
	let pillarWidthDeg = $state(1.9);
	let endstopActiveHigh = $state(true);
	let liveAvailable = $state(false);
	let endstopTriggered = $state<boolean | null>(null);
	let rawEndstopHigh = $state<boolean | null>(null);
	let currentAngle = $state<number | null>(null);
	let stepperPositionDegrees = $state<number | null>(null);
	let stepperMicrosteps = $state<number | null>(null);
	let stepperStopped = $state<boolean | null>(null);
	let homePinChannel = $state<number | null>(null);
	let digitalInputs = $state<Array<{ channel: number; raw_high: boolean }>>([]);
	let liveRequestInFlight = false;
	let calibrateAbortController: AbortController | null = null;

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function formatNumber(value: number | null, digits = 1): string {
		return value === null ? '--' : value.toFixed(digits);
	}

	function applyLiveStatus(payload: any) {
		liveAvailable = Boolean(payload?.live_available);
		endstopTriggered =
			typeof payload?.endstop_triggered === 'boolean' ? payload.endstop_triggered : null;
		rawEndstopHigh =
			typeof payload?.raw_endstop_high === 'boolean' ? payload.raw_endstop_high : null;
		if (typeof payload?.endstop_active_high === 'boolean') {
			endstopActiveHigh = payload.endstop_active_high;
		}
		homePinChannel =
			typeof payload?.home_pin_channel === 'number' && Number.isFinite(payload.home_pin_channel)
				? payload.home_pin_channel
				: null;
		digitalInputs = Array.isArray(payload?.digital_inputs)
			? payload.digital_inputs
					.filter(
						(entry: any): entry is { channel: number; raw_high: boolean } =>
							typeof entry?.channel === 'number' && typeof entry?.raw_high === 'boolean'
					)
					.map((entry: { channel: number; raw_high: boolean }) => ({
						channel: entry.channel,
						raw_high: entry.raw_high
					}))
			: [];
		currentAngle =
			typeof payload?.current_angle === 'number' && Number.isFinite(payload.current_angle)
				? payload.current_angle
				: null;
		stepperPositionDegrees =
			typeof payload?.stepper_position_degrees === 'number' &&
			Number.isFinite(payload.stepper_position_degrees)
				? payload.stepper_position_degrees
				: null;
		stepperMicrosteps =
			typeof payload?.stepper_microsteps === 'number' && Number.isFinite(payload.stepper_microsteps)
				? payload.stepper_microsteps
				: null;
		stepperStopped =
			typeof payload?.stepper_stopped === 'boolean' ? payload.stepper_stopped : null;
	}

	async function loadSettings() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			firstBinCenter = Number(payload?.chute?.first_bin_center ?? 8.4);
			pillarWidthDeg = Number(payload?.chute?.pillar_width_deg ?? 1.9);
			endstopActiveHigh = Boolean(payload?.chute?.endstop_active_high ?? true);
			void loadLiveStatus();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load chute settings';
		} finally {
			loading = false;
		}
	}

	async function loadLiveStatus() {
		if (liveRequestInFlight) return;
		liveRequestInFlight = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/chute/live`);
			if (!res.ok) throw new Error(await res.text());
			applyLiveStatus(await res.json());
		} catch {
			// Keep the last known live state during transient controller hiccups.
		} finally {
			liveRequestInFlight = false;
		}
	}

	async function saveSettings() {
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/chute`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					first_bin_center: firstBinCenter,
					pillar_width_deg: pillarWidthDeg,
					endstop_active_high: endstopActiveHigh
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			firstBinCenter = Number(payload?.settings?.first_bin_center ?? firstBinCenter);
			pillarWidthDeg = Number(payload?.settings?.pillar_width_deg ?? pillarWidthDeg);
			endstopActiveHigh = Boolean(payload?.settings?.endstop_active_high ?? endstopActiveHigh);
			statusMsg = payload?.message ?? 'Chute settings saved.';
			void loadLiveStatus();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save chute settings';
		} finally {
			saving = false;
		}
	}

	async function findEndstop() {
		calibrateAbortController?.abort();
		const abortController = new AbortController();
		calibrateAbortController = abortController;
		calibrating = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/chute/calibrate/find-endstop`,
				{ method: 'POST', signal: abortController.signal }
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			applyLiveStatus(payload?.status ?? payload);
			statusMsg =
				payload?.message ?? 'Step 1 complete. Chute moved slowly until the endstop was found.';
		} catch (e: any) {
			if (e?.name === 'AbortError') return;
			errorMsg = e.message ?? 'Failed to find chute endstop';
		} finally {
			if (calibrateAbortController === abortController) {
				calibrateAbortController = null;
				calibrating = false;
			}
		}
	}

	async function cancelFindEndstop() {
		canceling = true;
		errorMsg = null;
		statusMsg = '';
		calibrateAbortController?.abort();
		calibrateAbortController = null;
		calibrating = false;
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/chute/calibrate/cancel`,
				{ method: 'POST' }
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			applyLiveStatus(payload?.status ?? payload);
			statusMsg = payload?.message ?? 'Chute homing canceled.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to cancel chute homing';
		} finally {
			canceling = false;
		}
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ?? '__local__';
		if (machineKey !== loadedMachineKey) {
			loadedMachineKey = machineKey;
			void loadSettings();
		}
	});

	$effect(() => {
		loadedMachineKey;
		void loadLiveStatus();
	});

	onMount(() => {
		const interval = setInterval(() => {
			void loadLiveStatus();
		}, 500);
		return () => clearInterval(interval);
	});
</script>

<div class="flex flex-col gap-4">
	<div class="text-sm text-text-muted">
		These values define how the chute maps section/bin addresses to real angles after homing.
	</div>

			<div class="grid grid-cols-1 gap-3 border border-border bg-bg px-3 py-3 sm:grid-cols-2 xl:grid-cols-4">
		<div class="flex flex-col gap-1">
			<div class="text-xs text-text-muted">Endstop</div>
			<div
				class={`inline-flex w-fit rounded px-2 py-1 text-sm font-medium ${
					endstopTriggered === true
						? 'bg-green-500/15 text-green-700 dark:text-green-300'
						: endstopTriggered === false
							? 'bg-surface text-text'
							: 'bg-surface text-text-muted'
				}`}
			>
				{endstopTriggered === true
					? 'Triggered'
					: endstopTriggered === false
						? 'Not Triggered'
						: liveAvailable
							? 'Unknown'
							: 'Unavailable'}
			</div>
			<div class="text-xs text-text-muted">
				Raw pin: {rawEndstopHigh === null ? '--' : rawEndstopHigh ? 'High' : 'Low'}
			</div>
			{#if homePinChannel !== null}
				<div class="text-xs text-text-muted">
					Using input channel {homePinChannel}
				</div>
			{/if}
		</div>
		<div class="flex flex-col gap-1">
			<div class="text-xs text-text-muted">Current Chute Angle</div>
			<div class="text-sm font-medium text-text">
				{formatNumber(currentAngle)}°
			</div>
		</div>
		<div class="flex flex-col gap-1">
			<div class="text-xs text-text-muted">Stepper Position</div>
			<div class="text-sm font-medium text-text">
				{formatNumber(stepperPositionDegrees)}°
			</div>
		</div>
		<div class="flex flex-col gap-1">
			<div class="text-xs text-text-muted">Stepper State</div>
			<div class="text-sm font-medium text-text">
				{stepperStopped === null ? '--' : stepperStopped ? 'Stopped' : 'Moving'}{#if stepperMicrosteps !== null}
					{' '}
					<span class="ml-1 text-xs font-normal text-text-muted">
						({stepperMicrosteps} usteps)
					</span>
				{/if}
			</div>
		</div>
	</div>

	<div class="flex flex-col gap-3 border border-border bg-bg px-3 py-3">
		<div class="flex flex-col gap-1">
			<div class="text-sm font-medium text-text">Calibration Step 1</div>
			<div class="text-sm text-text-muted">
				Slowly home the chute until the endstop triggers, then zero the chute position from that reference.
			</div>
		</div>
		<div class="flex flex-wrap items-center gap-2">
			<button
				onclick={findEndstop}
				disabled={loading || saving || calibrating || canceling}
				class="cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				{calibrating ? 'Finding Endstop...' : 'Step 1: Find Endstop'}
			</button>
			<button
				onclick={cancelFindEndstop}
				disabled={!calibrating || canceling}
				class="w-full cursor-pointer border border-red-500 bg-red-500/20 px-3 py-1.5 text-sm text-red-600 hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto dark:text-red-400"
			>
				{canceling ? 'Canceling...' : 'Cancel Homing'}
			</button>
			<div class="text-xs text-text-muted">
				This moves the chute hardware. Cancel stops all steppers for safety.
			</div>
		</div>
	</div>

	{#if digitalInputs.length > 0}
		<div class="flex flex-col gap-2 border border-border bg-bg px-3 py-3">
			<div class="text-sm font-medium text-text">Distributor Inputs</div>
			<div class="text-xs text-text-muted">
				Live raw digital inputs from the distributor board for endstop debugging.
			</div>
			<div class="flex flex-wrap gap-2">
				{#each digitalInputs as input}
					<div class="rounded border border-border bg-surface px-2 py-1 text-xs text-text">
						IN{input.channel}: {input.raw_high ? 'High' : 'Low'}
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
		<label class="text-xs text-text">
			First Bin Center (deg)
			<input
				type="number"
				min="0"
				max="60"
				step="0.1"
				bind:value={firstBinCenter}
				disabled={loading || saving}
				class="mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
			/>
		</label>
		<label class="flex items-center gap-2 text-xs text-text sm:self-end sm:pb-2">
			<input
				type="checkbox"
				checked={endstopActiveHigh}
				onchange={(event) => (endstopActiveHigh = event.currentTarget.checked)}
				disabled={loading || saving || calibrating || canceling}
			/>
			Endstop active high
		</label>
		<label class="text-xs text-text">
			Pillar Width (deg)
			<input
				type="number"
				min="0"
				max="59.9"
				step="0.1"
				bind:value={pillarWidthDeg}
				disabled={loading || saving}
				class="mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
			/>
		</label>
	</div>

	<div class="flex flex-wrap items-center gap-2">
		<button
			onclick={saveSettings}
			disabled={loading || saving || calibrating || canceling}
			class="cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
		>
			{saving ? 'Saving...' : 'Save Chute Settings'}
		</button>
		<button
			onclick={loadSettings}
			disabled={loading || saving || calibrating || canceling}
			class="cursor-pointer border border-border bg-bg px-3 py-1.5 text-sm text-text hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
		>
			{loading ? 'Loading...' : 'Reload'}
		</button>
	</div>

	{#if errorMsg}
		<div class="text-sm text-red-600 dark:text-red-400">{errorMsg}</div>
	{:else if statusMsg}
		<div class="text-sm text-text-muted">{statusMsg}</div>
	{/if}
</div>
