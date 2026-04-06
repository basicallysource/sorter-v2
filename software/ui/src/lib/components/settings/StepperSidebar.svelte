<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import type { StepperKey } from '$lib/settings/stations';
	import { stepperLabels } from '$lib/settings/stations';
	import type { EndstopConfig } from '$lib/settings/stations';
	import {
		STEPPER_GEAR_RATIOS,
		loadStoredStepperPulseSetting,
		persistStoredStepperPulseSetting
	} from '$lib/settings/stepper-control';
	import { ChevronLeft, ChevronRight, ChevronDown, Home, Square, Cog } from 'lucide-svelte';
	import { onMount } from 'svelte';

	let {
		stepperKey,
		label = undefined,
		endstop = undefined,
		keyboardShortcuts = false
	}: {
		stepperKey: StepperKey;
		label?: string;
		endstop?: EndstopConfig;
		keyboardShortcuts?: boolean;
	} = $props();

	const manager = getMachinesContext();
	const displayLabel = $derived(label ?? stepperLabels[stepperKey]);
	const hasEndstop = $derived(!!endstop);

	// --- Machine tracking ---
	let loadedMachineKey = $state('');

	// --- Operation states ---
	let loading = $state(false);
	let saving = $state(false);
	let homing = $state(false);
	let canceling = $state(false);
	let calibrating = $state(false);
	let pulsing = $state<Record<string, boolean>>({});
	let stopping = $state(false);

	// --- Messages ---
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');

	// --- Live status ---
	let endstopTriggered = $state<boolean | null>(null);
	let currentPositionDegrees = $state<number | null>(null);
	let stepperMicrosteps = $state<number | null>(null);
	let stepperStopped = $state<boolean | null>(null);
	let liveRequestInFlight = false;

	// --- Stepper control (persisted per stepper) ---
	type PulseMode = 'duration' | 'degrees';

	let pulseMode = $state<PulseMode>('duration');
	let pulseDuration = $state(0.25);
	let pulseSpeed = $state(800);
	let pulseDegrees = $state(90);
	let pulseSettingsLoadedFor = $state<StepperKey | null>(null);

	$effect(() => {
		pulseMode = loadStoredStepperPulseSetting(stepperKey, 'pulseMode', 'duration');
		pulseDuration = loadStoredStepperPulseSetting(stepperKey, 'pulseDuration', 0.25);
		pulseSpeed = loadStoredStepperPulseSetting(stepperKey, 'pulseSpeed', 800);
		pulseDegrees = loadStoredStepperPulseSetting(stepperKey, 'pulseDegrees', 90);
		pulseSettingsLoadedFor = stepperKey;
	});

	$effect(() => {
		if (pulseSettingsLoadedFor !== stepperKey) return;
		persistStoredStepperPulseSetting(stepperKey, 'pulseMode', pulseMode);
	});
	$effect(() => {
		if (pulseSettingsLoadedFor !== stepperKey) return;
		persistStoredStepperPulseSetting(stepperKey, 'pulseDuration', pulseDuration);
	});
	$effect(() => {
		if (pulseSettingsLoadedFor !== stepperKey) return;
		persistStoredStepperPulseSetting(stepperKey, 'pulseSpeed', pulseSpeed);
	});
	$effect(() => {
		if (pulseSettingsLoadedFor !== stepperKey) return;
		persistStoredStepperPulseSetting(stepperKey, 'pulseDegrees', pulseDegrees);
	});

	const gearRatio = $derived(STEPPER_GEAR_RATIOS[stepperKey]);

	// --- Endstop settings ---
	let endstopActiveHigh = $state(false);
	let stepperDirectionInverted = $state(false);

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

	// --- Collapsible sections ---
	let driverSettingsOpen = $state(false);
	let endstopSettingsOpen = $state(false);

	// --- Homing/calibration ---
	let homeAbortController: AbortController | null = null;
	let calibrateResult = $state<{ steps_per_revolution: number } | null>(null);

	// --- Utilities ---

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

	let hardwareState = $state<string>('standby');

	async function fetchHardwareState() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/status`);
			if (res.ok) {
				const data = await res.json();
				hardwareState = data.hardware_state ?? 'standby';
			}
		} catch {
			// ignore
		}
	}

	function humanizeStepperError(message: string): string {
		if (message.includes('Controller not initialized')) {
			return 'Hardware not started. Press Start in the dashboard first.';
		}
		return message;
	}

	async function readErrorMessage(res: Response): Promise<string> {
		try {
			const data = await res.json();
			if (typeof data?.detail === 'string') return data.detail;
			if (typeof data?.message === 'string') return data.message;
		} catch {
			/* fall through */
		}
		try {
			return await res.text();
		} catch {
			return `Request failed with status ${res.status}`;
		}
	}

	function shouldIgnoreKeyboardShortcut(event: KeyboardEvent): boolean {
		if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return true;
		const target = event.target;
		if (!(target instanceof HTMLElement)) return false;
		if (target.isContentEditable) return true;
		return ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(target.tagName);
	}

	// --- Live status (endstop polling) ---

	function applyLiveStatus(payload: any) {
		endstopTriggered =
			typeof payload?.endstop_triggered === 'boolean' ? payload.endstop_triggered : null;
		currentPositionDegrees =
			typeof payload?.current_position_degrees === 'number' &&
			Number.isFinite(payload.current_position_degrees)
				? payload.current_position_degrees
				: null;
		stepperMicrosteps =
			typeof payload?.stepper_microsteps === 'number' &&
			Number.isFinite(payload.stepper_microsteps)
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
	}

	async function loadSettings() {
		if (!endstop) return;
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}${endstop.configEndpoint}`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			endstopActiveHigh = Boolean(payload?.endstop_active_high ?? false);
			stepperDirectionInverted = Boolean(payload?.stepper_direction_inverted ?? false);
			void loadLiveStatus();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load settings';
		} finally {
			loading = false;
		}
	}

	async function loadLiveStatus() {
		if (!endstop || liveRequestInFlight) return;
		liveRequestInFlight = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}${endstop.liveEndpoint}`);
			if (!res.ok) throw new Error(await res.text());
			applyLiveStatus(await res.json());
		} catch {
			// keep last known
		} finally {
			liveRequestInFlight = false;
		}
	}

	// --- Stepper pulse/stop ---

	async function pulse(direction: 'cw' | 'ccw') {
		if (pulseMode === 'degrees') {
			return moveDegrees(direction);
		}
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

	async function moveDegrees(direction: 'cw' | 'ccw') {
		const key = `${stepperKey}:${direction}`;
		if (pulsing[key]) return;
		pulsing = { ...pulsing, [key]: true };
		statusMsg = '';
		errorMsg = null;
		try {
			// Convert output degrees to motor degrees via gear ratio
			const motorDegrees = pulseDegrees * gearRatio * (direction === 'ccw' ? -1 : 1);
			const params = new URLSearchParams({
				stepper: stepperKey,
				degrees: String(motorDegrees),
				speed: String(pulseSpeed)
			});
			const res = await fetch(
				`${currentBackendBaseUrl()}/stepper/move-degrees?${params.toString()}`,
				{ method: 'POST' }
			);
			if (!res.ok) {
				errorMsg = humanizeStepperError(await readErrorMessage(res));
				return;
			}
			statusMsg = `Moving ${pulseDegrees}° ${direction.toUpperCase()}.`;
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

	// --- Homing ---

	async function homeToEndstop() {
		if (!endstop) return;
		homeAbortController?.abort();
		const abortController = new AbortController();
		homeAbortController = abortController;
		homing = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}${endstop.homeEndpoint}`, {
				method: 'POST',
				signal: abortController.signal
			});
			if (!res.ok) throw new Error(await readErrorMessage(res));
			const payload = await res.json();
			applyLiveStatus(payload?.status ?? payload);
			statusMsg = payload?.message ?? 'Homed and zeroed.';
		} catch (e: any) {
			if (e?.name === 'AbortError') return;
			errorMsg = e.message ?? 'Failed to home';
		} finally {
			if (homeAbortController === abortController) {
				homeAbortController = null;
				homing = false;
			}
		}
	}

	async function cancelHoming() {
		if (!endstop) return;
		canceling = true;
		errorMsg = null;
		statusMsg = '';
		homeAbortController?.abort();
		homeAbortController = null;
		homing = false;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}${endstop.homeCancelEndpoint}`, {
				method: 'POST'
			});
			if (!res.ok) throw new Error(await readErrorMessage(res));
			const payload = await res.json();
			applyLiveStatus(payload?.status ?? payload);
			statusMsg = payload?.message ?? 'Homing canceled.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to cancel homing';
		} finally {
			canceling = false;
		}
	}

	async function calibrate() {
		if (!endstop?.calibrateEndpoint) return;
		calibrating = true;
		calibrateResult = null;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}${endstop.calibrateEndpoint}`, {
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

	// --- Endstop settings ---

	async function saveEndstopSettings() {
		if (!endstop) return;
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}${endstop.configEndpoint}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					endstop_active_high: endstopActiveHigh,
					stepper_direction_inverted: stepperDirectionInverted
				})
			});
			if (!res.ok) throw new Error(await readErrorMessage(res));
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

	// --- TMC driver settings ---

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
			// Save direction invert via config endpoint if endstop is set
			if (endstop) {
				const dirRes = await fetch(`${currentBackendBaseUrl()}${endstop.configEndpoint}`, {
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
			}

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

	// --- Keyboard shortcuts ---

	function handleWindowKeydown(event: KeyboardEvent) {
		if (!keyboardShortcuts) return;
		if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
		if (shouldIgnoreKeyboardShortcut(event)) return;
		event.preventDefault();
		void pulse(event.key === 'ArrowRight' ? 'cw' : 'ccw');
	}

	// --- Lifecycle ---

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ??
			'__local__';
		if (machineKey !== loadedMachineKey) {
			loadedMachineKey = machineKey;
			if (endstop) void loadSettings();
			tmcLoaded = false;
			if (driverSettingsOpen) void loadTmcSettings();
		}
	});

	onMount(() => {
		if (endstop) void loadSettings();
		void fetchHardwareState();
		const interval = setInterval(() => {
			if (endstop) void loadLiveStatus();
			void refreshDrvStatus();
			void fetchHardwareState();
		}, 500);
		return () => clearInterval(interval);
	});
</script>

<svelte:window onkeydown={handleWindowKeydown} />

<aside
	class="flex h-full min-w-0 flex-col border border-border bg-bg"
>
	<!-- Header -->
	<div class="border-b border-border bg-surface px-4 py-3">
		<div class="flex items-start gap-3">
			<div
				class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-bg text-text"
			>
				<Cog size={16} />
			</div>
			<div class="min-w-0">
				<div class="text-sm font-semibold text-text">{displayLabel}</div>
				<div
					class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-text-muted"
				>
					<span
						>{stepperStopped === null ? '--' : stepperStopped ? 'Stopped' : 'Moving'}</span
					>
					<span>·</span>
					<span>{formatNumber(currentPositionDegrees)}°</span>
					<span>·</span>
					<span>{stepperMicrosteps ?? '--'} µs</span>
				</div>
				{#if hasEndstop && endstopTriggered !== null}
					<div
						class="mt-1 text-xs {endstopTriggered
							? 'text-[#00852B] dark:text-green-400'
							: 'text-text-muted'}"
					>
						Endstop: {endstopTriggered ? 'Triggered' : 'Not Triggered'}
					</div>
				{/if}
			</div>
		</div>
	</div>

	<!-- Scrollable content -->
	<div class="flex flex-1 flex-col gap-4 overflow-y-auto px-4 py-4">
		<!-- Controls -->
		<div class="flex flex-col gap-1">
			<div class="text-sm font-medium text-text">Controls</div>
			{#if keyboardShortcuts}
				<div class="text-xs text-text-muted">
					Arrow keys also jog this stepper.
				</div>
			{/if}
		</div>

		<div class="grid grid-cols-3 gap-2">
			<button
				onclick={() => pulse('ccw')}
				disabled={Boolean(pulsing[`${stepperKey}:ccw`]) || homing || canceling}
				class="inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			>
				<ChevronLeft size={16} />
				CCW
			</button>
			<button
				onclick={stopStepper}
				disabled={stopping || homing || canceling}
				class="inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 border border-[#D01012] bg-[#D01012]/10 px-3 text-sm text-[#D01012] transition-colors hover:bg-[#D01012]/20 disabled:cursor-not-allowed disabled:opacity-50 dark:text-red-400"
			>
				<Square size={14} />
				Stop
			</button>
			<button
				onclick={() => pulse('cw')}
				disabled={Boolean(pulsing[`${stepperKey}:cw`]) || homing || canceling}
				class="inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			>
				CW
				<ChevronRight size={16} />
			</button>
		</div>

		<!-- Pulse mode toggle -->
		<div class="flex gap-1">
			<button
				onclick={() => (pulseMode = 'duration')}
				class="flex-1 cursor-pointer border px-2 py-1 text-xs transition-colors {pulseMode === 'duration'
					? 'border-border bg-surface font-medium text-text'
					: 'border-border/50 bg-transparent text-text-muted hover:bg-surface'}"
			>
				Duration
			</button>
			<button
				onclick={() => (pulseMode = 'degrees')}
				class="flex-1 cursor-pointer border px-2 py-1 text-xs transition-colors {pulseMode === 'degrees'
					? 'border-border bg-surface font-medium text-text'
					: 'border-border/50 bg-transparent text-text-muted hover:bg-surface'}"
			>
				Degrees
			</button>
		</div>

		<div class="grid grid-cols-2 gap-3">
			{#if pulseMode === 'duration'}
				<label class="text-xs text-text">
					Duration (s)
					<input
						type="number"
						min="0.05"
						max="5"
						step="0.05"
						bind:value={pulseDuration}
						class="mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
					/>
				</label>
			{:else}
				<label class="text-xs text-text">
					Degrees (output)
					<input
						type="number"
						min="1"
						max="3600"
						step="1"
						bind:value={pulseDegrees}
						class="mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
					/>
				</label>
			{/if}
			<label class="text-xs text-text">
				Speed
				<input
					type="number"
					min="1"
					step="50"
					bind:value={pulseSpeed}
					class="mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>
		</div>
		{#if pulseMode === 'degrees' && gearRatio !== 1}
			<div class="text-xs text-text-muted">
				Ratio {gearRatio.toFixed(2)}:1 — {pulseDegrees}° output = {(pulseDegrees * gearRatio).toFixed(1)}° motor
			</div>
		{/if}

		<!-- Homing (only if endstop) -->
		{#if hasEndstop}
			<div class="border-t border-border pt-4"></div>

			<div class="flex flex-col gap-1">
				<div class="text-sm font-medium text-text">Homing</div>
				<div class="text-xs text-text-muted">
					Find the endstop slowly, or cancel and stop all steppers if the wrong motor moves.
				</div>
			</div>

			<div class="flex flex-col gap-2">
				<button
					onclick={homeToEndstop}
					disabled={loading || saving || homing || canceling}
					class="inline-flex cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
				>
					<Home size={14} />
					{homing ? 'Homing...' : 'Home to Endstop'}
				</button>
				<button
					onclick={cancelHoming}
					disabled={!homing || canceling}
					class="cursor-pointer border border-[#D01012] bg-[#D01012]/20 px-3 py-2 text-sm text-[#D01012] hover:bg-[#D01012]/30 disabled:cursor-not-allowed disabled:opacity-50 dark:text-red-400"
				>
					{canceling ? 'Canceling...' : 'Cancel Homing'}
				</button>
				{#if endstop?.calibrateEndpoint}
					<button
						onclick={calibrate}
						disabled={endstopTriggered !== true || homing || calibrating || canceling}
						class="inline-flex cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						{calibrating ? 'Calibrating...' : 'Calibrate Full Rotation'}
					</button>
					{#if calibrateResult}
						<div class="text-xs text-text-muted">
							Result: {calibrateResult.steps_per_revolution} steps/rev
						</div>
					{/if}
				{/if}
			</div>
		{/if}

		<!-- Driver Settings (collapsible) -->
		<div class="border-t border-border pt-4"></div>

		<button
			onclick={() => {
				driverSettingsOpen = !driverSettingsOpen;
				if (driverSettingsOpen && !tmcLoaded) void loadTmcSettings();
			}}
			class="flex w-full cursor-pointer items-center justify-between"
		>
			<div class="text-sm font-medium text-text">Driver Settings</div>
			<ChevronDown
				size={16}
				class="text-text-muted transition-transform {driverSettingsOpen
					? 'rotate-180'
					: ''}"
			/>
		</button>

		{#if driverSettingsOpen}
			{#if tmcLoading}
				<div class="text-sm text-text-muted">
					Loading driver state...
				</div>
			{:else}
				<div class="flex flex-col gap-3">
					<label class="flex flex-col gap-1 text-xs text-text">
						Run Current (IRUN): {tmcIrun}
						<input type="range" min="0" max="31" bind:value={tmcIrun} class="w-full" />
					</label>

					<label class="flex flex-col gap-1 text-xs text-text">
						Hold Current (IHOLD): {tmcIhold}
						<input type="range" min="0" max="31" bind:value={tmcIhold} class="w-full" />
					</label>

					<label class="flex flex-col gap-1 text-xs text-text">
						Microstepping
						<select
							bind:value={tmcMicrosteps}
							class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
						>
							{#each [1, 2, 4, 8, 16, 32, 64, 128, 256] as ms}
								<option value={ms}>1/{ms}</option>
							{/each}
						</select>
					</label>

					<label class="flex items-center gap-2 text-sm text-text">
						<input type="checkbox" bind:checked={tmcStealthchop} />
						StealthChop
					</label>

					<label class="flex items-center gap-2 text-sm text-text">
						<input type="checkbox" bind:checked={tmcCoolstep} />
						CoolStep
					</label>

					{#if hasEndstop}
						<label class="flex items-center gap-2 text-sm text-text">
							<input
								type="checkbox"
								checked={stepperDirectionInverted}
								onchange={(event) =>
									(stepperDirectionInverted = event.currentTarget.checked)}
							/>
							Invert stepper direction
						</label>
					{/if}

					<button
						onclick={saveTmcSettings}
						disabled={tmcSaving}
						class="cursor-pointer border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						{tmcSaving ? 'Applying...' : 'Apply Driver Settings'}
					</button>

					{#if tmcDrvStatus}
						<div class="flex flex-col gap-1">
							<div
								class="text-xs uppercase tracking-[0.18em] text-text-muted"
							>
								DRV_STATUS
							</div>
							<div class="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
								<div
									class={tmcDrvStatus.ot
										? 'font-semibold text-[#D01012]'
										: 'text-text-muted'}
								>
									Overtemp: {tmcDrvStatus.ot ? 'YES' : 'No'}
								</div>
								<div
									class={tmcDrvStatus.otpw
										? 'font-semibold text-yellow-500'
										: 'text-text-muted'}
								>
									OT Pre-warn: {tmcDrvStatus.otpw ? 'YES' : 'No'}
								</div>
								<div
									class={tmcDrvStatus.s2ga
										? 'font-semibold text-[#D01012]'
										: 'text-text-muted'}
								>
									Short A: {tmcDrvStatus.s2ga ? 'YES' : 'No'}
								</div>
								<div
									class={tmcDrvStatus.s2gb
										? 'font-semibold text-[#D01012]'
										: 'text-text-muted'}
								>
									Short B: {tmcDrvStatus.s2gb ? 'YES' : 'No'}
								</div>
								<div
									class={tmcDrvStatus.ola
										? 'font-semibold text-yellow-500'
										: 'text-text-muted'}
								>
									Open A: {tmcDrvStatus.ola ? 'YES' : 'No'}
								</div>
								<div
									class={tmcDrvStatus.olb
										? 'font-semibold text-yellow-500'
										: 'text-text-muted'}
								>
									Open B: {tmcDrvStatus.olb ? 'YES' : 'No'}
								</div>
								<div class="text-text-muted">
									StealthChop: {tmcDrvStatus.stealth ? 'Active' : 'Off'}
								</div>
								<div class="text-text-muted">
									Standstill: {tmcDrvStatus.stst ? 'Yes' : 'No'}
								</div>
								<div class="text-text-muted">
									CS Actual: {tmcDrvStatus.cs_actual}
								</div>
								<div class="text-text-muted">
									SG Result: {tmcDrvStatus.sg_result}
								</div>
								<div
									class="col-span-2 {tmcDrvStatus.ot
										? 'font-semibold text-[#D01012]'
										: tmcDrvStatus.otpw
											? 'font-semibold text-yellow-500'
											: 'text-text-muted'}"
								>
									Temp: {tmcDrvStatus.ot
										? '>157°C SHUTDOWN'
										: tmcDrvStatus.t157
											? '>157°C'
											: tmcDrvStatus.t150
												? '>150°C'
												: tmcDrvStatus.t143
													? '>143°C'
													: tmcDrvStatus.t120
														? '>120°C'
														: '<120°C'}
								</div>
							</div>
						</div>
					{/if}
				</div>
			{/if}
		{/if}

		<!-- Endstop Settings (collapsible, only if endstop) -->
		{#if hasEndstop}
			<div class="border-t border-border pt-4"></div>

			<button
				onclick={() => (endstopSettingsOpen = !endstopSettingsOpen)}
				class="flex w-full cursor-pointer items-center justify-between"
			>
				<div class="text-sm font-medium text-text">Endstop Settings</div>
				<ChevronDown
					size={16}
					class="text-text-muted transition-transform {endstopSettingsOpen
						? 'rotate-180'
						: ''}"
				/>
			</button>

			{#if endstopSettingsOpen}
				<div class="text-sm text-text-muted">
					Flip this if the endstop reads backwards.
				</div>

				<label class="flex items-center gap-2 text-sm text-text">
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
					class="cursor-pointer border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
				>
					{saving ? 'Saving...' : 'Save Endstop Settings'}
				</button>
			{/if}
		{/if}

		<!-- Status / Error footer -->
		<div class="mt-auto">
			{#if errorMsg}
				<div class="text-sm text-[#D01012] dark:text-red-400">{errorMsg}</div>
			{:else if statusMsg}
				<div class="text-sm text-text-muted">{statusMsg}</div>
			{:else if homing}
				<div class="text-sm text-[#D01012]">Homing to endstop...</div>
			{:else if calibrating}
				<div class="text-sm text-[#D01012]">Calibrating full rotation...</div>
			{/if}
		</div>
	</div>
</aside>
