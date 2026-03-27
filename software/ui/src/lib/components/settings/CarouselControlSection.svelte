<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import type { StepperKey } from '$lib/settings/stations';
	import { ChevronLeft, ChevronRight, ChevronDown, Home, Square } from 'lucide-svelte';
	import { onMount } from 'svelte';

	let {
		stepperKey = 'carousel' as StepperKey
	}: {
		stepperKey?: StepperKey;
	} = $props();

	const manager = getMachinesContext();

	// --- Endstop / live state ---
	let loadedMachineKey = $state('');
	let loading = $state(false);
	let saving = $state(false);
	let homing = $state(false);
	let canceling = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let endstopActiveHigh = $state(false);
	let stepperDirectionInverted = $state(false);
	let endstopTriggered = $state<boolean | null>(null);
	let currentPositionDegrees = $state<number | null>(null);
	let stepperMicrosteps = $state<number | null>(null);
	let stepperStopped = $state<boolean | null>(null);
	let boundStepperName = $state<string | null>(null);
	let boundStepperChannel = $state<number | null>(null);
	let liveRequestInFlight = false;
	let homeAbortController: AbortController | null = null;
	let calibrating = $state(false);
	let calibrateResult = $state<{ steps_per_revolution: number } | null>(null);

	// --- Stepper control ---
	let pulseDuration = $state(0.25);
	let pulseSpeed = $state(800);
	let pulsing = $state<Record<string, boolean>>({});
	let stopping = $state(false);

	// --- Collapsible sections ---
	let endstopSettingsOpen = $state(false);
	let driverSettingsOpen = $state(false);

	// --- TMC driver settings ---
	let tmcIrun = $state(16);
	let tmcIhold = $state(8);
	let tmcMicrosteps = $state(8);
	let tmcStealthchop = $state(true);
	let tmcCoolstep = $state(false);
	let tmcDrvStatus = $state<Record<string, any> | null>(null);
	let tmcLoading = $state(false);
	let tmcSaving = $state(false);
	let tmcLoaded = false;

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

	// --- Endstop API ---
	function applyLiveStatus(payload: any) {
		endstopTriggered =
			typeof payload?.endstop_triggered === 'boolean' ? payload.endstop_triggered : null;
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
		if (!driverSettingsOpen) {
			stepperDirectionInverted =
				typeof payload?.stepper_direction_inverted === 'boolean'
					? payload.stepper_direction_inverted
					: stepperDirectionInverted;
		}
		boundStepperName = typeof payload?.bound_stepper_name === 'string' ? payload.bound_stepper_name : null;
		boundStepperChannel =
			typeof payload?.bound_stepper_channel === 'number' &&
			Number.isFinite(payload.bound_stepper_channel)
				? payload.bound_stepper_channel
				: null;
	}

	async function loadSettings() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/carousel`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			endstopActiveHigh = Boolean(payload?.endstop_active_high ?? false);
			stepperDirectionInverted = Boolean(payload?.stepper_direction_inverted ?? false);
			void loadLiveStatus();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load carousel settings';
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
			// keep last known
		} finally {
			liveRequestInFlight = false;
		}
	}

	async function saveEndstopSettings() {
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/carousel`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					endstop_active_high: endstopActiveHigh,
					stepper_direction_inverted: stepperDirectionInverted
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			endstopActiveHigh = Boolean(payload?.settings?.endstop_active_high ?? endstopActiveHigh);
			stepperDirectionInverted = Boolean(
				payload?.settings?.stepper_direction_inverted ?? stepperDirectionInverted
			);
			applyLiveStatus(payload?.status ?? payload);
			statusMsg = payload?.message ?? 'Settings saved.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save settings';
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
			statusMsg = payload?.message ?? 'Homed and zeroed.';
		} catch (e: any) {
			if (e?.name === 'AbortError') return;
			errorMsg = e.message ?? 'Failed to home carousel';
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
			statusMsg = payload?.message ?? 'Homing canceled.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to cancel homing';
		} finally {
			canceling = false;
		}
	}

	async function calibrateCarousel() {
		calibrating = true;
		calibrateResult = null;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/carousel/calibrate`, {
				method: 'POST'
			});
			if (!res.ok) throw new Error(await readErrorMessage(res));
			const payload = await res.json();
			applyLiveStatus(payload?.status ?? payload);
			calibrateResult = { steps_per_revolution: payload.steps_per_revolution };
			statusMsg = payload?.message ?? `Calibrated: ${payload.steps_per_revolution} steps/rev.`;
		} catch (e: any) {
			errorMsg = e.message ?? 'Calibration failed';
		} finally {
			calibrating = false;
		}
	}

	// --- Stepper API ---
	function humanizeStepperError(message: string): string {
		if (message.includes('Controller not initialized')) {
			return 'Machine controller not running. Start the machine process first.';
		}
		return message;
	}

	async function readErrorMessage(res: Response): Promise<string> {
		try {
			const data = await res.json();
			if (typeof data?.detail === 'string') return data.detail;
			if (typeof data?.message === 'string') return data.message;
		} catch { /* fall through */ }
		try {
			return await res.text();
		} catch {
			return `Request failed with status ${res.status}`;
		}
	}

	async function pulse(direction: 'cw' | 'ccw') {
		const key = `${stepperKey}:${direction}`;
		if (pulsing[key]) return;
		pulsing = { ...pulsing, [key]: true };
		statusMsg = '';
		errorMsg = null;
		try {
			const params = new URLSearchParams({
				stepper: stepperKey,
				direction,
				duration_s: String(pulseDuration),
				speed: String(pulseSpeed)
			});
			const res = await fetch(`${currentBackendBaseUrl()}/stepper/pulse?${params.toString()}`, {
				method: 'POST'
			});
			if (!res.ok) {
				errorMsg = humanizeStepperError(await readErrorMessage(res));
				return;
			}
			statusMsg = `Pulsing ${direction.toUpperCase()}.`;
		} catch {
			errorMsg = `${direction.toUpperCase()} request failed.`;
		} finally {
			pulsing = { ...pulsing, [key]: false };
		}
	}

	async function stopStepper() {
		stopping = true;
		statusMsg = '';
		errorMsg = null;
		try {
			const params = new URLSearchParams({ stepper: stepperKey });
			const res = await fetch(`${currentBackendBaseUrl()}/stepper/stop?${params.toString()}`, {
				method: 'POST'
			});
			if (!res.ok) {
				errorMsg = humanizeStepperError(await readErrorMessage(res));
				return;
			}
			statusMsg = 'Stopped.';
		} catch {
			errorMsg = 'Stop request failed.';
		} finally {
			stopping = false;
		}
	}

	// --- TMC API ---
	async function loadTmcSettings() {
		tmcLoading = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/stepper/${stepperKey}/tmc`);
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (data.irun !== null) tmcIrun = data.irun;
			if (data.ihold !== null) tmcIhold = data.ihold;
			if (data.microsteps !== null) tmcMicrosteps = data.microsteps;
			if (data.stealthchop !== null) tmcStealthchop = data.stealthchop;
			if (data.coolstep !== null) tmcCoolstep = data.coolstep;
			tmcDrvStatus = data.drv_status ?? null;
			tmcLoaded = true;
		} catch {
			// silent
		} finally {
			tmcLoading = false;
		}
	}

	async function saveTmcSettings() {
		tmcSaving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			// Save direction invert via carousel config endpoint
			const dirRes = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/carousel`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					endstop_active_high: endstopActiveHigh,
					stepper_direction_inverted: stepperDirectionInverted
				})
			});
			if (!dirRes.ok) {
				errorMsg = await readErrorMessage(dirRes);
				return;
			}

			// Save TMC register settings
			const res = await fetch(`${currentBackendBaseUrl()}/api/stepper/${stepperKey}/tmc`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					irun: tmcIrun,
					ihold: tmcIhold,
					microsteps: tmcMicrosteps,
					stealthchop: tmcStealthchop,
					coolstep: tmcCoolstep
				})
			});
			if (!res.ok) {
				errorMsg = await readErrorMessage(res);
				return;
			}
			const data = await res.json();
			if (data.irun !== null) tmcIrun = data.irun;
			if (data.ihold !== null) tmcIhold = data.ihold;
			if (data.microsteps !== null) tmcMicrosteps = data.microsteps;
			if (data.stealthchop !== null) tmcStealthchop = data.stealthchop;
			if (data.coolstep !== null) tmcCoolstep = data.coolstep;
			tmcDrvStatus = data.drv_status ?? null;
			statusMsg = 'Driver settings applied.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save driver settings';
		} finally {
			tmcSaving = false;
		}
	}

	async function refreshDrvStatus() {
		if (!driverSettingsOpen || !tmcLoaded) return;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/stepper/${stepperKey}/tmc`);
			if (!res.ok) return;
			const data = await res.json();
			tmcDrvStatus = data.drv_status ?? null;
		} catch {
			// silent
		}
	}

	function shouldIgnoreKeyboardShortcut(event: KeyboardEvent): boolean {
		if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return true;
		const target = event.target;
		if (!(target instanceof HTMLElement)) return false;
		if (target.isContentEditable) return true;
		return ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(target.tagName);
	}

	function handleWindowKeydown(event: KeyboardEvent) {
		if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
		if (shouldIgnoreKeyboardShortcut(event)) return;
		event.preventDefault();
		void pulse(event.key === 'ArrowRight' ? 'cw' : 'ccw');
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ?? '__local__';
		if (machineKey !== loadedMachineKey) {
			loadedMachineKey = machineKey;
			void loadSettings();
			tmcLoaded = false;
			if (driverSettingsOpen) void loadTmcSettings();
		}
	});

	onMount(() => {
		void loadSettings();
		const interval = setInterval(() => {
			void loadLiveStatus();
			void refreshDrvStatus();
		}, 500);
		return () => clearInterval(interval);
	});
</script>

<svelte:window onkeydown={handleWindowKeydown} />

<div class="-mx-4 -my-4 grid lg:grid-cols-[minmax(0,1fr)_18rem]">
	<div class="flex flex-col gap-4 px-4 py-4">
		<div class="flex flex-col gap-1">
			<div class="dark:text-text-dark text-base font-semibold text-text">Carousel</div>
			<div class="dark:text-text-muted-dark text-sm text-text-muted">
				Live carousel position and endstop state. Left and right arrow keys also jog this stepper.
			</div>
		</div>

		<div class="dark:border-border-dark dark:bg-bg-dark flex flex-col gap-4 border border-border bg-bg px-4 py-4">
			<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
				<div class="flex flex-col gap-2">
					<div class="dark:text-text-muted-dark text-xs uppercase tracking-[0.18em] text-text-muted">
						Live Status
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
								: '--'}
					</div>
				</div>
				<div class="dark:text-text-muted-dark max-w-sm text-sm text-text-muted">
					Use this readout to confirm whether the endstop and jog direction match the real hardware.
				</div>
			</div>

		<div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
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
				<div class="dark:border-border-dark dark:bg-surface-dark flex flex-col gap-1 border border-border bg-surface px-3 py-3">
					<div class="dark:text-text-muted-dark text-xs text-text-muted">Triggered</div>
				<div class="dark:text-text-dark text-base font-semibold text-text">
					{endstopTriggered === true ? 'Yes' : endstopTriggered === false ? 'No' : '--'}
				</div>
			</div>
			<div class="dark:border-border-dark dark:bg-surface-dark flex flex-col gap-1 border border-border bg-surface px-3 py-3">
				<div class="dark:text-text-muted-dark text-xs text-text-muted">Bound Motor</div>
				<div class="dark:text-text-dark text-base font-semibold text-text">
					{boundStepperName ? `${boundStepperName}${boundStepperChannel === null ? '' : ` · ch${boundStepperChannel}`}` : '--'}
				</div>
			</div>
		</div>
	</div>
	</div>

	<aside class="dark:border-border-dark dark:bg-surface-dark flex flex-col gap-4 border-t border-border bg-surface px-4 py-4 lg:border-l lg:border-t-0">
		<div class="flex flex-col gap-1">
			<div class="dark:text-text-dark text-sm font-medium text-text">Controls</div>
			<div class="dark:text-text-muted-dark text-sm text-text-muted">
				Jog, stop, home, and configure the carousel from here.
			</div>
		</div>

		<div class="grid grid-cols-3 gap-2">
			<button
				onclick={() => pulse('ccw')}
				disabled={Boolean(pulsing[`${stepperKey}:ccw`]) || homing || canceling}
				class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			>
				<ChevronLeft size={16} />
				CCW
			</button>
			<button
				onclick={stopStepper}
				disabled={stopping || homing || canceling}
				class="inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 border border-red-500 bg-red-500/10 px-3 text-sm text-red-600 transition-colors hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-50 dark:text-red-400"
			>
				<Square size={14} />
				Stop
			</button>
			<button
				onclick={() => pulse('cw')}
				disabled={Boolean(pulsing[`${stepperKey}:cw`]) || homing || canceling}
				class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			>
				CW
				<ChevronRight size={16} />
			</button>
		</div>

		<div class="grid grid-cols-2 gap-3">
			<label class="dark:text-text-dark text-xs text-text">
				Duration (s)
				<input
					type="number"
					min="0.05"
					max="5"
					step="0.05"
					bind:value={pulseDuration}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>
			<label class="dark:text-text-dark text-xs text-text">
				Speed
				<input
					type="number"
					min="1"
					step="50"
					bind:value={pulseSpeed}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>
		</div>

		<div class="dark:border-border-dark border-t border-border pt-4"></div>

		<div class="flex flex-col gap-1">
			<div class="dark:text-text-dark text-sm font-medium text-text">Homing</div>
			<div class="dark:text-text-muted-dark text-sm text-text-muted">
				Find the endstop slowly, or cancel and stop all steppers if the wrong motor moves.
			</div>
		</div>

		<div class="flex flex-col gap-2">
			<button
				onclick={homeCarousel}
				disabled={loading || saving || homing || canceling}
				class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark inline-flex cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			>
				<Home size={14} />
				{homing ? 'Homing Carousel...' : 'Home to Endstop'}
			</button>
			<button
				onclick={cancelCarouselHoming}
				disabled={!homing || canceling}
				class="cursor-pointer border border-red-500 bg-red-500/20 px-3 py-2 text-sm text-red-600 hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-50 dark:text-red-400"
			>
				{canceling ? 'Canceling...' : 'Cancel Homing'}
			</button>
			<button
				onclick={calibrateCarousel}
				disabled={endstopTriggered !== true || homing || calibrating || canceling}
				class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark inline-flex cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			>
				{calibrating ? 'Calibrating...' : 'Calibrate Full Rotation'}
			</button>
		</div>

		<!-- Driver Settings (collapsible) -->
		<div class="dark:border-border-dark border-t border-border pt-4"></div>

		<button
			onclick={() => {
				driverSettingsOpen = !driverSettingsOpen;
				if (driverSettingsOpen && !tmcLoaded) void loadTmcSettings();
			}}
			class="flex w-full cursor-pointer items-center justify-between"
		>
			<div class="dark:text-text-dark text-sm font-medium text-text">Driver Settings</div>
			<ChevronDown size={16} class="dark:text-text-muted-dark text-text-muted transition-transform {driverSettingsOpen ? 'rotate-180' : ''}" />
		</button>

		{#if driverSettingsOpen}
			{#if tmcLoading}
				<div class="dark:text-text-muted-dark text-sm text-text-muted">Loading driver state...</div>
			{:else}
				<div class="flex flex-col gap-3">
					<label class="dark:text-text-dark flex flex-col gap-1 text-xs text-text">
						Run Current (IRUN): {tmcIrun}
						<input
							type="range"
							min="0"
							max="31"
							bind:value={tmcIrun}
							class="w-full"
						/>
					</label>

					<label class="dark:text-text-dark flex flex-col gap-1 text-xs text-text">
						Hold Current (IHOLD): {tmcIhold}
						<input
							type="range"
							min="0"
							max="31"
							bind:value={tmcIhold}
							class="w-full"
						/>
					</label>

					<label class="dark:text-text-dark flex flex-col gap-1 text-xs text-text">
						Microstepping
						<select
							bind:value={tmcMicrosteps}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark border border-border bg-bg px-2 py-1.5 text-sm text-text"
						>
							{#each [1, 2, 4, 8, 16, 32, 64, 128, 256] as ms}
								<option value={ms}>1/{ms}</option>
							{/each}
						</select>
					</label>

					<label class="dark:text-text-dark flex items-center gap-2 text-sm text-text">
						<input type="checkbox" bind:checked={tmcStealthchop} />
						StealthChop
					</label>

					<label class="dark:text-text-dark flex items-center gap-2 text-sm text-text">
						<input type="checkbox" bind:checked={tmcCoolstep} />
						CoolStep
					</label>

					<label class="dark:text-text-dark flex items-center gap-2 text-sm text-text">
						<input
							type="checkbox"
							checked={stepperDirectionInverted}
							onchange={(event) => (stepperDirectionInverted = event.currentTarget.checked)}
						/>
						Invert stepper direction
					</label>

					<button
						onclick={saveTmcSettings}
						disabled={tmcSaving}
						class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark cursor-pointer border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						{tmcSaving ? 'Applying...' : 'Apply Driver Settings'}
					</button>

					{#if tmcDrvStatus}
						<div class="flex flex-col gap-1">
							<div class="dark:text-text-muted-dark text-xs uppercase tracking-[0.18em] text-text-muted">
								DRV_STATUS
							</div>
							<div class="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
								<div class={tmcDrvStatus.ot ? 'font-semibold text-red-500' : 'dark:text-text-muted-dark text-text-muted'}>
									Overtemp: {tmcDrvStatus.ot ? 'YES' : 'No'}
								</div>
								<div class={tmcDrvStatus.otpw ? 'font-semibold text-yellow-500' : 'dark:text-text-muted-dark text-text-muted'}>
									OT Pre-warn: {tmcDrvStatus.otpw ? 'YES' : 'No'}
								</div>
								<div class={tmcDrvStatus.s2ga ? 'font-semibold text-red-500' : 'dark:text-text-muted-dark text-text-muted'}>
									Short A: {tmcDrvStatus.s2ga ? 'YES' : 'No'}
								</div>
								<div class={tmcDrvStatus.s2gb ? 'font-semibold text-red-500' : 'dark:text-text-muted-dark text-text-muted'}>
									Short B: {tmcDrvStatus.s2gb ? 'YES' : 'No'}
								</div>
								<div class={tmcDrvStatus.ola ? 'font-semibold text-yellow-500' : 'dark:text-text-muted-dark text-text-muted'}>
									Open A: {tmcDrvStatus.ola ? 'YES' : 'No'}
								</div>
								<div class={tmcDrvStatus.olb ? 'font-semibold text-yellow-500' : 'dark:text-text-muted-dark text-text-muted'}>
									Open B: {tmcDrvStatus.olb ? 'YES' : 'No'}
								</div>
								<div class="dark:text-text-muted-dark text-text-muted">
									StealthChop: {tmcDrvStatus.stealth ? 'Active' : 'Off'}
								</div>
								<div class="dark:text-text-muted-dark text-text-muted">
									Standstill: {tmcDrvStatus.stst ? 'Yes' : 'No'}
								</div>
								<div class="dark:text-text-muted-dark text-text-muted">
									CS Actual: {tmcDrvStatus.cs_actual}
								</div>
								<div class="dark:text-text-muted-dark text-text-muted">
									SG Result: {tmcDrvStatus.sg_result}
								</div>
							</div>
						</div>
					{/if}
				</div>
			{/if}
		{/if}

		<!-- Endstop Settings (collapsible) -->
		<div class="dark:border-border-dark border-t border-border pt-4"></div>

		<button
			onclick={() => endstopSettingsOpen = !endstopSettingsOpen}
			class="flex w-full cursor-pointer items-center justify-between"
		>
			<div class="dark:text-text-dark text-sm font-medium text-text">Endstop Settings</div>
			<ChevronDown size={16} class="dark:text-text-muted-dark text-text-muted transition-transform {endstopSettingsOpen ? 'rotate-180' : ''}" />
		</button>

		{#if endstopSettingsOpen}
			<div class="dark:text-text-muted-dark text-sm text-text-muted">
				Flip this if the endstop reads backwards.
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

			<button
				onclick={saveEndstopSettings}
				disabled={loading || saving || homing || canceling}
				class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark cursor-pointer border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			>
				{saving ? 'Saving...' : 'Save Endstop Settings'}
			</button>
		{/if}

		{#if errorMsg}
			<div class="text-sm text-red-600 dark:text-red-400">{errorMsg}</div>
		{:else if statusMsg}
			<div class="dark:text-text-muted-dark text-sm text-text-muted">{statusMsg}</div>
		{:else if homing}
			<div class="text-sm text-blue-500">Homing to endstop...</div>
		{:else if calibrating}
			<div class="text-sm text-blue-500">Calibrating full rotation...</div>
		{/if}
	</aside>
</div>
