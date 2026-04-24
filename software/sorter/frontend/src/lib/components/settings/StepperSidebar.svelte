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
	import {
		loadStepperDirections,
		loadStepperEndpoint,
		loadStepperTmcSettings,
		moveStepperDegrees,
		postStepperEndpoint,
		pulseStepper,
		saveStepperDirection as saveStepperDirectionRequest,
		saveStepperTmcSettings,
		stopStepperMotion,
		type StepperDriverMode
	} from '$lib/settings/stepper-service';
	import { Cog } from 'lucide-svelte';
	import { onMount } from 'svelte';
	import StepperPulseControls from './stepper/StepperPulseControls.svelte';
	import StepperHoming from './stepper/StepperHoming.svelte';
	import StepperDriverSettings from './stepper/StepperDriverSettings.svelte';
	import StepperEndstopSettings from './stepper/StepperEndstopSettings.svelte';
	import StepperChuteOperation from './stepper/StepperChuteOperation.svelte';

	let {
		stepperKey,
		label = undefined,
		gearRatioOverride = undefined,
		endstop = undefined,
		keyboardShortcuts = false
	}: {
		stepperKey: StepperKey;
		label?: string;
		gearRatioOverride?: number;
		endstop?: EndstopConfig;
		keyboardShortcuts?: boolean;
	} = $props();

	const manager = getMachinesContext();
	const displayLabel = $derived(label ?? stepperLabels[stepperKey]);
	const hasEndstop = $derived(!!endstop);
	const isChute = $derived(stepperKey === 'chute');

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

	const gearRatio = $derived(gearRatioOverride ?? STEPPER_GEAR_RATIOS[stepperKey]);

	// --- Endstop settings ---
	let endstopActiveHigh = $state(false);
	let stepperDirectionInverted = $state(false);
	let chuteFirstBinCenter = $state(8.25);
	let chutePillarWidthDeg = $state(8.25);
	let chuteOperatingSpeed = $state(3000);

	// --- TMC driver settings ---
	let tmcIrun = $state(16);
	let tmcIhold = $state(8);
	let tmcMicrosteps = $state(8);
	let tmcDriverMode = $state<StepperDriverMode>('stealthchop');
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

	const hardwareState = $derived(
		manager.selectedMachine?.systemStatus?.hardware_state ?? 'standby'
	);

	function humanizeStepperError(message: string): string {
		if (message.includes('Controller not initialized')) {
			return 'Hardware not started. Press Start in the dashboard first.';
		}
		return message;
	}

	function normalizeDriverMode(data: any): StepperDriverMode {
		if (
			data?.driver_mode === 'off' ||
			data?.driver_mode === 'stealthchop' ||
			data?.driver_mode === 'coolstep'
		) {
			return data.driver_mode;
		}
		if (data?.coolstep && !data?.stealthchop) return 'coolstep';
		if (data?.stealthchop) return 'stealthchop';
		return 'off';
	}

	function shouldIgnoreKeyboardShortcut(event: KeyboardEvent): boolean {
		if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return true;
		const target = event.target;
		if (!(target instanceof HTMLElement)) return false;
		if (target.isContentEditable) return true;
		return ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(target.tagName);
	}

	function findStepperDirectionEntry(payload: any): Record<string, any> | null {
		if (!Array.isArray(payload?.steppers)) return null;
		return (
			payload.steppers.find(
				(entry: any) => entry && typeof entry === 'object' && entry.name === stepperKey
			) ?? null
		);
	}

	function applyStepperDirectionEntry(entry: Record<string, any> | null) {
		if (driverSettingsOpen || !entry) return;
		if (typeof entry.live_inverted === 'boolean') {
			stepperDirectionInverted = entry.live_inverted;
			return;
		}
		if (typeof entry.inverted === 'boolean') {
			stepperDirectionInverted = entry.inverted;
		}
	}

	async function loadStepperDirection() {
		const payload = await loadStepperDirections(currentBackendBaseUrl());
		applyStepperDirectionEntry(findStepperDirectionEntry(payload));
	}

	async function saveStepperDirection() {
		const payload = await saveStepperDirectionRequest(
			currentBackendBaseUrl(),
			stepperKey,
			stepperDirectionInverted
		);
		applyStepperDirectionEntry(findStepperDirectionEntry(payload));
		if (typeof payload?.inverted === 'boolean' && !driverSettingsOpen) {
			stepperDirectionInverted = payload.inverted;
		}
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
			typeof payload?.stepper_microsteps === 'number' && Number.isFinite(payload.stepper_microsteps)
				? payload.stepper_microsteps
				: null;
		stepperStopped = typeof payload?.stepper_stopped === 'boolean' ? payload.stepper_stopped : null;
		if (!driverSettingsOpen) {
			stepperDirectionInverted =
				typeof payload?.stepper_direction_inverted === 'boolean'
					? payload.stepper_direction_inverted
					: stepperDirectionInverted;
		}
	}

	async function loadSettings() {
		loading = true;
		errorMsg = null;
		try {
			if (endstop) {
				const payload = await loadStepperEndpoint(currentBackendBaseUrl(), endstop.configEndpoint);
				endstopActiveHigh = Boolean(payload?.endstop_active_high ?? false);
				if (stepperKey === 'chute') {
					chuteFirstBinCenter = Number(payload?.first_bin_center ?? chuteFirstBinCenter);
					chutePillarWidthDeg = Number(payload?.pillar_width_deg ?? chutePillarWidthDeg);
					chuteOperatingSpeed = Number(
						payload?.operating_speed_microsteps_per_second ?? chuteOperatingSpeed
					);
				}
				stepperDirectionInverted = Boolean(
					payload?.stepper_direction_inverted ?? stepperDirectionInverted
				);
				void loadLiveStatus();
			}
			await loadStepperDirection();
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
			applyLiveStatus(await loadStepperEndpoint(currentBackendBaseUrl(), endstop.liveEndpoint));
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
			await pulseStepper(currentBackendBaseUrl(), stepperKey, direction, {
				durationSeconds: pulseDuration,
				speed: pulseSpeed
			});
			statusMsg = `Pulsing ${direction.toUpperCase()}.`;
		} catch (e: any) {
			errorMsg = humanizeStepperError(e.message ?? `${direction.toUpperCase()} request failed.`);
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
			await moveStepperDegrees(currentBackendBaseUrl(), stepperKey, {
				motorDegrees,
				speed: pulseSpeed
			});
			statusMsg = `Moving ${pulseDegrees}° ${direction.toUpperCase()}.`;
		} catch (e: any) {
			errorMsg = humanizeStepperError(e.message ?? `${direction.toUpperCase()} request failed.`);
		} finally {
			pulsing = { ...pulsing, [key]: false };
		}
	}

	async function stopStepper() {
		stopping = true;
		statusMsg = '';
		errorMsg = null;
		try {
			await stopStepperMotion(currentBackendBaseUrl(), stepperKey);
			statusMsg = 'Stopped.';
		} catch (e: any) {
			errorMsg = humanizeStepperError(e.message ?? 'Stop request failed.');
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
			const payload = await postStepperEndpoint(currentBackendBaseUrl(), endstop.homeEndpoint, {
				signal: abortController.signal
			});
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
			const payload = await postStepperEndpoint(
				currentBackendBaseUrl(),
				endstop.homeCancelEndpoint
			);
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
			const payload = await postStepperEndpoint(currentBackendBaseUrl(), endstop.calibrateEndpoint);
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

	async function saveChuteSettings(customMessage?: string) {
		if (!endstop || stepperKey !== 'chute') return;
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const payload = await postStepperEndpoint(currentBackendBaseUrl(), endstop.configEndpoint, {
				payload: {
					first_bin_center: chuteFirstBinCenter,
					pillar_width_deg: chutePillarWidthDeg,
					endstop_active_high: endstopActiveHigh,
					operating_speed_microsteps_per_second: chuteOperatingSpeed
				}
			});
			endstopActiveHigh = Boolean(payload?.settings?.endstop_active_high ?? endstopActiveHigh);
			chuteFirstBinCenter = Number(payload?.settings?.first_bin_center ?? chuteFirstBinCenter);
			chutePillarWidthDeg = Number(payload?.settings?.pillar_width_deg ?? chutePillarWidthDeg);
			chuteOperatingSpeed = Number(
				payload?.settings?.operating_speed_microsteps_per_second ?? chuteOperatingSpeed
			);
			applyLiveStatus(payload?.status ?? payload);
			statusMsg = customMessage ?? payload?.message ?? 'Chute settings saved.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save chute settings';
		} finally {
			saving = false;
		}
	}

	async function saveEndstopSettings() {
		if (!endstop) return;
		if (stepperKey === 'chute') {
			await saveChuteSettings('Endstop settings saved.');
			return;
		}
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const payload = await postStepperEndpoint(currentBackendBaseUrl(), endstop.configEndpoint, {
				payload: {
					endstop_active_high: endstopActiveHigh,
					stepper_direction_inverted: stepperDirectionInverted
				}
			});
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
			const data = await loadStepperTmcSettings(currentBackendBaseUrl(), stepperKey);
			if (data.irun !== null) tmcIrun = data.irun;
			if (data.ihold !== null) tmcIhold = data.ihold;
			if (data.microsteps !== null) tmcMicrosteps = data.microsteps;
			tmcDriverMode = normalizeDriverMode(data);
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
			await saveStepperDirection();

			const data = await saveStepperTmcSettings(currentBackendBaseUrl(), stepperKey, {
				irun: tmcIrun,
				ihold: tmcIhold,
				microsteps: tmcMicrosteps,
				driver_mode: tmcDriverMode
			});
			if (data.irun !== null) tmcIrun = data.irun;
			if (data.ihold !== null) tmcIhold = data.ihold;
			if (data.microsteps !== null) tmcMicrosteps = data.microsteps;
			tmcDriverMode = normalizeDriverMode(data);
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
			const data = await loadStepperTmcSettings(currentBackendBaseUrl(), stepperKey);
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
			void loadSettings();
			tmcLoaded = false;
			if (driverSettingsOpen) void loadTmcSettings();
		}
	});

	onMount(() => {
		void loadSettings();
		const interval = setInterval(() => {
			if (endstop) void loadLiveStatus();
			void refreshDrvStatus();
		}, 500);
		return () => clearInterval(interval);
	});
</script>

<svelte:window onkeydown={handleWindowKeydown} />

<aside class="flex h-full min-w-0 flex-col border border-border bg-bg">
	<!-- Header -->
	<div class="border-b border-border bg-surface px-4 py-3">
		<div class="flex items-start gap-3">
			<div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-bg text-text">
				<Cog size={16} />
			</div>
			<div class="min-w-0">
				<div class="text-sm font-semibold text-text">{displayLabel}</div>
				<div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-text-muted">
					<span>{stepperStopped === null ? '--' : stepperStopped ? 'Stopped' : 'Moving'}</span>
					<span>·</span>
					<span>{formatNumber(currentPositionDegrees)}°</span>
					<span>·</span>
					<span>{stepperMicrosteps ?? '--'} µs</span>
				</div>
				{#if hasEndstop && endstopTriggered !== null}
					<div
						class="mt-1 text-xs {endstopTriggered
							? 'text-success dark:text-green-400'
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
		<StepperPulseControls
			{stepperKey}
			{keyboardShortcuts}
			{pulsing}
			{homing}
			{canceling}
			{stopping}
			bind:pulseMode
			bind:pulseDuration
			bind:pulseSpeed
			bind:pulseDegrees
			{gearRatio}
			onPulse={pulse}
			onStop={stopStepper}
		/>

		{#if isChute}
			<StepperChuteOperation
				{loading}
				{saving}
				{homing}
				{canceling}
				bind:chuteOperatingSpeed
				onSave={() => void saveChuteSettings('Distributor operating speed saved.')}
			/>
		{/if}

		{#if hasEndstop}
			<StepperHoming
				{loading}
				{saving}
				{homing}
				{canceling}
				{calibrating}
				{endstopTriggered}
				{calibrateResult}
				hasCalibrateEndpoint={Boolean(endstop?.calibrateEndpoint)}
				onHome={homeToEndstop}
				onCancel={cancelHoming}
				onCalibrate={calibrate}
			/>
		{/if}

		<StepperDriverSettings
			bind:open={driverSettingsOpen}
			loading={tmcLoading}
			saving={tmcSaving}
			{hasEndstop}
			bind:tmcIrun
			bind:tmcIhold
			bind:tmcMicrosteps
			bind:tmcDriverMode
			bind:stepperDirectionInverted
			{tmcDrvStatus}
			onToggle={() => {
				driverSettingsOpen = !driverSettingsOpen;
				if (driverSettingsOpen && !tmcLoaded) void loadTmcSettings();
			}}
			onSave={saveTmcSettings}
		/>

		{#if hasEndstop}
			<StepperEndstopSettings
				bind:open={endstopSettingsOpen}
				{loading}
				{saving}
				{homing}
				{canceling}
				bind:endstopActiveHigh
				onToggle={() => (endstopSettingsOpen = !endstopSettingsOpen)}
				onSave={saveEndstopSettings}
			/>
		{/if}

		<!-- Status / Error footer -->
		<div class="mt-auto">
			{#if errorMsg}
				<div class="text-sm text-danger dark:text-red-400">{errorMsg}</div>
			{:else if statusMsg}
				<div class="text-sm text-text-muted">{statusMsg}</div>
			{:else if homing}
				<div class="text-sm text-primary">Homing to endstop...</div>
			{:else if calibrating}
				<div class="text-sm text-primary">Calibrating full rotation...</div>
			{/if}
		</div>
	</div>
</aside>
