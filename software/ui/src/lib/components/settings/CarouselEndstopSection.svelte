<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount } from 'svelte';

	const manager = getMachinesContext();

	let loadedMachineKey = $state('');
	let loading = $state(false);
	let saving = $state(false);
	let homing = $state(false);
	let canceling = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let endstopActiveHigh = $state(false);
	let liveAvailable = $state(false);
	let endstopTriggered = $state<boolean | null>(null);
	let rawEndstopHigh = $state<boolean | null>(null);
	let homePinChannel = $state<number | null>(null);
	let currentPositionDegrees = $state<number | null>(null);
	let stepperMicrosteps = $state<number | null>(null);
	let stepperStopped = $state<boolean | null>(null);
	let liveRequestInFlight = false;
	let homeAbortController: AbortController | null = null;

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
		homePinChannel =
			typeof payload?.home_pin_channel === 'number' && Number.isFinite(payload.home_pin_channel)
				? payload.home_pin_channel
				: null;
		currentPositionDegrees =
			typeof payload?.current_position_degrees === 'number' &&
			Number.isFinite(payload.current_position_degrees)
				? payload.current_position_degrees
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
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/carousel`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			endstopActiveHigh = Boolean(payload?.endstop_active_high ?? false);
			homePinChannel =
				typeof payload?.home_pin_channel === 'number' && Number.isFinite(payload.home_pin_channel)
					? payload.home_pin_channel
					: homePinChannel;
			void loadLiveStatus();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load carousel endstop settings';
		} finally {
			loading = false;
		}
	}

	async function loadLiveStatus() {
		if (liveRequestInFlight) return;
		liveRequestInFlight = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/carousel/live`);
			if (!res.ok) throw new Error(await res.text());
			applyLiveStatus(await res.json());
		} catch {
			// Keep the last known status during transient controller hiccups.
		} finally {
			liveRequestInFlight = false;
		}
	}

	async function saveSettings() {
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/carousel`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					endstop_active_high: endstopActiveHigh
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			endstopActiveHigh = Boolean(payload?.settings?.endstop_active_high ?? endstopActiveHigh);
			applyLiveStatus(payload?.status ?? payload);
			statusMsg = payload?.message ?? 'Carousel endstop settings saved.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save carousel endstop settings';
		} finally {
			saving = false;
		}
	}

	async function homeCarousel() {
		homeAbortController?.abort();
		const abortController = new AbortController();
		homeAbortController = abortController;
		homing = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/carousel/home`, {
				method: 'POST',
				signal: abortController.signal
			});
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			applyLiveStatus(payload?.status ?? payload);
			statusMsg = payload?.message ?? 'Carousel homed to the endstop and zeroed.';
		} catch (e: any) {
			if (e?.name === 'AbortError') return;
			errorMsg = e.message ?? 'Failed to home carousel to endstop';
		} finally {
			if (homeAbortController === abortController) {
				homeAbortController = null;
				homing = false;
			}
		}
	}

	async function cancelCarouselHoming() {
		canceling = true;
		errorMsg = null;
		statusMsg = '';
		homeAbortController?.abort();
		homeAbortController = null;
		homing = false;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/carousel/home/cancel`, {
				method: 'POST'
			});
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			applyLiveStatus(payload?.status ?? payload);
			statusMsg = payload?.message ?? 'Carousel homing canceled.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to cancel carousel homing';
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

	onMount(() => {
		void loadSettings();
		const interval = setInterval(() => {
			void loadLiveStatus();
		}, 500);
		return () => clearInterval(interval);
	});
</script>

<div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_18rem]">
	<div class="flex flex-col gap-4">
		<div class="dark:border-border-dark dark:bg-bg-dark flex flex-col gap-4 border border-border bg-bg px-4 py-4">
			<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
				<div class="flex flex-col gap-2">
					<div class="dark:text-text-muted-dark text-xs uppercase tracking-[0.18em] text-text-muted">
						Live Endstop Status
					</div>
					<div
						class={`inline-flex w-fit rounded px-3 py-1.5 text-sm font-medium ${
							endstopTriggered === true
								? 'bg-green-500/15 text-green-700 dark:text-green-300'
								: endstopTriggered === false
									? 'bg-surface text-text dark:bg-surface-dark dark:text-text-dark'
									: 'bg-surface text-text-muted dark:bg-surface-dark dark:text-text-muted-dark'
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
				</div>
				<div class="dark:text-text-muted-dark max-w-sm text-sm text-text-muted">
					The carousel home switch is expected on feeder input channel 2 (`Z-stop / IO25`).
				</div>
			</div>

			<div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
				<div class="dark:border-border-dark dark:bg-surface-dark flex flex-col gap-1 border border-border bg-surface px-3 py-3">
					<div class="dark:text-text-muted-dark text-xs text-text-muted">Triggered</div>
					<div class="dark:text-text-dark text-base font-semibold text-text">
						{endstopTriggered === true
							? 'Yes'
							: endstopTriggered === false
								? 'No'
								: '--'}
					</div>
				</div>
				<div class="dark:border-border-dark dark:bg-surface-dark flex flex-col gap-1 border border-border bg-surface px-3 py-3">
					<div class="dark:text-text-muted-dark text-xs text-text-muted">Degrees</div>
					<div class="dark:text-text-dark text-base font-semibold text-text">
						{formatNumber(currentPositionDegrees)}°
					</div>
				</div>
				<div class="dark:border-border-dark dark:bg-surface-dark flex flex-col gap-1 border border-border bg-surface px-3 py-3">
					<div class="dark:text-text-muted-dark text-xs text-text-muted">Stepper</div>
					<div class="dark:text-text-dark text-base font-semibold text-text">
						{stepperStopped === null ? '--' : stepperStopped ? 'Stopped' : 'Moving'}
					</div>
				</div>
				<div class="dark:border-border-dark dark:bg-surface-dark flex flex-col gap-1 border border-border bg-surface px-3 py-3">
					<div class="dark:text-text-muted-dark text-xs text-text-muted">Microsteps</div>
					<div class="dark:text-text-dark text-base font-semibold text-text">
						{stepperMicrosteps === null ? '--' : stepperMicrosteps}
					</div>
				</div>
			</div>

			<div class="flex flex-wrap items-center gap-x-4 gap-y-2">
				<div class="dark:text-text-muted-dark text-sm text-text-muted">
					Raw pin: {rawEndstopHigh === null ? '--' : rawEndstopHigh ? 'High' : 'Low'}
				</div>
				{#if homePinChannel !== null}
					<div class="dark:text-text-muted-dark text-sm text-text-muted">
						Input channel {homePinChannel}
					</div>
				{/if}
			</div>
		</div>
	</div>

	<aside class="dark:border-border-dark dark:bg-bg-dark flex flex-col gap-4 border border-border bg-bg px-4 py-4">
		<div class="flex flex-col gap-1">
			<div class="dark:text-text-dark text-sm font-medium text-text">Endstop Settings</div>
			<div class="dark:text-text-muted-dark text-sm text-text-muted">
				Flip polarity here if the live triggered state is backwards.
			</div>
		</div>

		<label class="dark:text-text-dark flex items-center gap-2 text-sm text-text">
			<input
				type="checkbox"
				checked={endstopActiveHigh}
				onchange={(event) => (endstopActiveHigh = event.currentTarget.checked)}
				disabled={loading || saving || homing || canceling}
			/>
			Endstop active high
		</label>

		<div class="dark:text-text-muted-dark text-xs text-text-muted">
			Turn this on when the input goes `High` at the moment the optical sensor is physically
			triggered.
		</div>

		<div class="flex flex-col gap-2">
			<button
				onclick={saveSettings}
				disabled={loading || saving || homing || canceling}
				class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				{saving ? 'Saving...' : 'Save Endstop Setting'}
			</button>
			<button
				onclick={loadSettings}
				disabled={loading || saving || homing || canceling}
				class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark cursor-pointer border border-border bg-bg px-3 py-1.5 text-sm text-text hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			>
				{loading ? 'Loading...' : 'Reload'}
			</button>
		</div>

		<div class="dark:border-border-dark border-t border-border pt-4"></div>

		<div class="flex flex-col gap-1">
			<div class="dark:text-text-dark text-sm font-medium text-text">Carousel Homing</div>
			<div class="dark:text-text-muted-dark text-sm text-text-muted">
				Move the carousel slowly until the endstop triggers, then zero the carousel position.
			</div>
		</div>

		<div class="flex flex-col gap-2">
			<button
				onclick={homeCarousel}
				disabled={loading || saving || homing || canceling}
				class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				{homing ? 'Homing Carousel...' : 'Home to Endstop'}
			</button>
			<button
				onclick={cancelCarouselHoming}
				disabled={!homing || canceling}
				class="cursor-pointer border border-red-500 bg-red-500/20 px-3 py-1.5 text-sm text-red-600 hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-50 dark:text-red-400"
			>
				{canceling ? 'Canceling...' : 'Cancel Homing'}
			</button>
		</div>

		<div class="dark:text-text-muted-dark text-xs text-text-muted">
			Cancel stops all steppers for safety.
		</div>

		{#if errorMsg}
			<div class="text-sm text-red-600 dark:text-red-400">{errorMsg}</div>
		{:else if statusMsg}
			<div class="dark:text-text-muted-dark text-sm text-text-muted">{statusMsg}</div>
		{/if}
	</aside>
</div>
