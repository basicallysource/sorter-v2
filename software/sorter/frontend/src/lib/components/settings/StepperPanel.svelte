<!--
	One motor on a settings page: its state, the buttons that move it by hand and
	its driver settings. A motor under a channel's camera is one panel as wide as
	the camera, its driver settings folded away. The chute has a page of its own,
	so each of its jobs (operating speed, stress test, driver settings, endstop)
	is a panel that is always shown, and homing is the two buttons at the top.
-->
<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import type { StepperKey } from '$lib/settings/stations';
	import { stepperLabels } from '$lib/settings/stations';
	import type { EndstopConfig } from '$lib/settings/stations';
	import {
		DIRECTION_WORDS,
		STEPPER_GEAR_RATIOS,
		loadStoredStepperPulseSetting,
		persistStoredStepperPulseSetting
	} from '$lib/settings/stepper-control';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Disclosure from '$lib/components/ui/Disclosure.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { onMount } from 'svelte';
	import StepperPulseControls from './stepper/StepperPulseControls.svelte';
	import StepperHoming from './stepper/StepperHoming.svelte';
	import StepperDriverSettings from './stepper/StepperDriverSettings.svelte';
	import StepperDrvStatusGrid from './stepper/StepperDrvStatusGrid.svelte';
	import StepperEndstopSettings from './stepper/StepperEndstopSettings.svelte';
	import StepperChuteOperation from './stepper/StepperChuteOperation.svelte';
	import StepperChuteStressTest from './stepper/StepperChuteStressTest.svelte';

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
	// Where the motor's StallGuard is tuned, for the driver settings' link to it.
	const stallguardHref = $derived(
		isChute
			? '/settings/chute/stallguard'
			: stepperKey === 'c_channel_4'
				? '/settings/classification-channel/stallguard'
				: undefined
	);

	// --- Machine tracking ---
	let loadedMachineKey = $state('');

	// --- Operation states ---
	let loading = $state(false);
	let saving = $state(false);
	let homing = $state(false);
	let canceling = $state(false);
	let pulsing = $state<Record<string, boolean>>({});
	let stopping = $state(false);

	// --- Messages ---
	// What the last action said, shown where that action's button is.
	type Scope = 'motor' | 'speed' | 'driver' | 'endstop';
	let scope = $state<Scope>('motor');
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');

	// --- Live status ---
	let endstopTriggered = $state<boolean | null>(null);
	let currentPositionDegrees = $state<number | null>(null);
	let stepperMicrosteps = $state<number | null>(null);
	let stepperStopped = $state<boolean | null>(null);
	let chuteOutputAngle = $state<number | null>(null);
	let chuteStepperDegrees = $state<number | null>(null);
	let chuteHomed = $state<boolean | null>(null);
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
	let tmcStealthchop = $state(true);
	let tmcCoolstep = $state(false);
	let sgEnabled = $state(false);
	let sgThrs = $state(50);
	let sgTcoolthrs = $state(150);
	let tmcDrvStatus = $state<Record<string, any> | null>(null);
	let tmcStalled = $state(false);
	let tmcClearingStall = $state(false);
	let tmcLoading = $state(false);
	// The driver's settings could not be read: they are not shown, so the defaults
	// in the fields are never applied over what the driver has.
	let tmcReadFailed = $state(false);
	let tmcSaving = $state(false);
	let tmcLoaded = false;

	// --- Collapsible sections ---
	let driverSettingsOpen = $state(false);
	let endstopSettingsOpen = $state(false);
	// The driver settings are on the page: always on the chute's, once opened elsewhere.
	const driverShown = $derived(isChute || driverSettingsOpen);
	// Once the direction is read, live polling stops overwriting what is being
	// edited in the driver settings.
	let directionRead = false;

	// --- Homing ---
	let homeAbortController: AbortController | null = null;

	// --- Utilities ---

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	function formatNumber(value: number | null, digits = 1): string {
		return value === null ? '--' : value.toFixed(digits);
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

	function findStepperDirectionEntry(payload: any): Record<string, any> | null {
		if (!Array.isArray(payload?.steppers)) return null;
		return (
			payload.steppers.find(
				(entry: any) => entry && typeof entry === 'object' && entry.name === stepperKey
			) ?? null
		);
	}

	function setDirectionInverted(value: boolean) {
		stepperDirectionInverted = value;
		directionRead = true;
	}

	function applyStepperDirectionEntry(entry: Record<string, any> | null) {
		if ((driverShown && directionRead) || !entry) return;
		if (typeof entry.live_inverted === 'boolean') {
			setDirectionInverted(entry.live_inverted);
			return;
		}
		if (typeof entry.inverted === 'boolean') {
			setDirectionInverted(entry.inverted);
		}
	}

	async function loadStepperDirection() {
		const res = await fetch(`${currentBackendBaseUrl()}/api/setup-wizard/stepper-directions`);
		if (!res.ok) throw new Error(await readErrorMessage(res));
		const payload = await res.json();
		applyStepperDirectionEntry(findStepperDirectionEntry(payload));
	}

	async function saveStepperDirection() {
		const res = await fetch(
			`${currentBackendBaseUrl()}/api/setup-wizard/stepper-directions/${stepperKey}`,
			{
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ inverted: stepperDirectionInverted })
			}
		);
		if (!res.ok) throw new Error(await readErrorMessage(res));
		const payload = await res.json();
		applyStepperDirectionEntry(findStepperDirectionEntry(payload));
		if (typeof payload?.inverted === 'boolean' && !driverShown) {
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
			typeof payload?.stepper_microsteps === 'number' &&
			Number.isFinite(payload.stepper_microsteps)
				? payload.stepper_microsteps
				: null;
		stepperStopped =
			typeof payload?.stepper_stopped === 'boolean' ? payload.stepper_stopped : null;
		if (
			!(driverShown && directionRead) &&
			typeof payload?.stepper_direction_inverted === 'boolean'
		) {
			setDirectionInverted(payload.stepper_direction_inverted);
		}
		// chute-specific fields
		chuteOutputAngle =
			typeof payload?.current_angle === 'number' && Number.isFinite(payload.current_angle)
				? payload.current_angle
				: null;
		chuteStepperDegrees =
			typeof payload?.stepper_position_degrees === 'number' &&
			Number.isFinite(payload.stepper_position_degrees)
				? payload.stepper_position_degrees
				: null;
		chuteHomed = typeof payload?.homed === 'boolean' ? payload.homed : null;
	}

	async function loadSettings() {
		loading = true;
		directionRead = false;
		errorMsg = null;
		try {
			if (endstop) {
				const res = await fetch(`${currentBackendBaseUrl()}${endstop.configEndpoint}`);
				if (!res.ok) throw new Error(await readErrorMessage(res));
				const payload = await res.json();
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
			scope = 'motor';
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
		scope = 'motor';
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
			statusMsg = `Pulsing ${DIRECTION_WORDS[direction]}.`;
		} catch {
			errorMsg = `The ${DIRECTION_WORDS[direction]} request failed.`;
		} finally {
			pulsing = { ...pulsing, [key]: false };
		}
	}

	async function moveDegrees(direction: 'cw' | 'ccw') {
		const key = `${stepperKey}:${direction}`;
		if (pulsing[key]) return;
		pulsing = { ...pulsing, [key]: true };
		scope = 'motor';
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
			statusMsg = `Moving ${pulseDegrees}° ${DIRECTION_WORDS[direction]}.`;
		} catch {
			errorMsg = `The ${DIRECTION_WORDS[direction]} request failed.`;
		} finally {
			pulsing = { ...pulsing, [key]: false };
		}
	}

	async function stopStepper() {
		stopping = true;
		scope = 'motor';
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
		scope = 'motor';
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
		scope = 'motor';
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

	// --- Endstop settings ---

	async function saveChuteSettings(from: Scope, customMessage?: string) {
		if (!endstop || stepperKey !== 'chute') return;
		saving = true;
		scope = from;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}${endstop.configEndpoint}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					first_bin_center: chuteFirstBinCenter,
					pillar_width_deg: chutePillarWidthDeg,
					endstop_active_high: endstopActiveHigh,
					operating_speed_microsteps_per_second: chuteOperatingSpeed
				})
			});
			if (!res.ok) throw new Error(await readErrorMessage(res));
			const payload = await res.json();
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
			await saveChuteSettings('endstop', 'Endstop settings saved.');
			return;
		}
		saving = true;
		scope = 'endstop';
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
		tmcReadFailed = false;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/stepper/${stepperKey}/tmc`);
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (data.irun !== null) tmcIrun = data.irun;
			if (data.ihold !== null) tmcIhold = data.ihold;
			if (data.microsteps !== null) tmcMicrosteps = data.microsteps;
			if (data.stealthchop !== null) tmcStealthchop = data.stealthchop;
			if (data.coolstep !== null) tmcCoolstep = data.coolstep;
			if (data.stallguard) {
				sgEnabled = !!data.stallguard.enabled;
				if (typeof data.stallguard.sgthrs === 'number') sgThrs = data.stallguard.sgthrs;
				if (typeof data.stallguard.tcoolthrs === 'number') sgTcoolthrs = data.stallguard.tcoolthrs;
			}
			tmcDrvStatus = data.drv_status ?? null;
			tmcStalled = !!data.stalled;
			tmcLoaded = true;
		} catch {
			tmcReadFailed = true;
		} finally {
			tmcLoading = false;
		}
	}

	async function loadStallState() {
		// Cheap per-poll read so the stall banner shows at the top without expanding
		// Driver Settings, and updates live while you're on the page.
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/steppers/stall-state`);
			if (!res.ok) return;
			const data = await res.json();
			const entry = data.steppers?.[stepperKey];
			if (entry) tmcStalled = !!entry.stalled;
		} catch {
			// silent
		}
	}

	async function clearStall() {
		tmcClearingStall = true;
		scope = 'motor';
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/stepper/${stepperKey}/clear-stall`,
				{ method: 'POST' }
			);
			if (!res.ok) {
				errorMsg = await readErrorMessage(res);
				return;
			}
			tmcStalled = false;
			statusMsg = 'Stall cleared.';
			// Re-read so the badge reflects whether it re-latched (still jammed).
			await loadStallState();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to clear stall';
		} finally {
			tmcClearingStall = false;
		}
	}

	async function saveTmcSettings() {
		tmcSaving = true;
		scope = 'driver';
		errorMsg = null;
		statusMsg = '';
		try {
			await saveStepperDirection();

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

			const sgRes = await fetch(
				`${currentBackendBaseUrl()}/stepper/${stepperKey}/stallguard-config`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						sgthrs: sgThrs,
						tcoolthrs: sgTcoolthrs,
						enabled: sgEnabled
					})
				}
			);
			if (!sgRes.ok) {
				errorMsg = await readErrorMessage(sgRes);
				return;
			}
			statusMsg = 'Driver settings applied.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save driver settings';
		} finally {
			tmcSaving = false;
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
			if (driverShown) void loadTmcSettings();
		}
	});

	onMount(() => {
		void loadSettings();
		void loadStallState();
		const interval = setInterval(() => {
			if (endstop) void loadLiveStatus();
			void loadStallState();
		}, 500);
		return () => clearInterval(interval);
	});

	// Opening the driver settings reads them from the driver the first time.
	$effect(() => {
		if (driverShown && !tmcLoaded) void loadTmcSettings();
	});
</script>

<svelte:window onkeydown={handleWindowKeydown} />

<!-- What the last action said, by the button it came from. -->
{#snippet feedback(forScope: Scope)}
	{#if scope === forScope}
		{#if errorMsg}
			<p class="text-danger-ink">{errorMsg}</p>
		{:else if statusMsg}
			<p class="text-ink-muted">{statusMsg}</p>
		{:else if forScope === 'motor' && homing}
			<p class="flex items-center gap-2 text-primary-ink">
				<Spinner size={14} /> Homing to the endstop
			</p>
		{/if}
	{/if}
{/snippet}
{#snippet speedMessage()}{@render feedback('speed')}{/snippet}

{#snippet driverSettings()}
	{#if tmcReadFailed}
		<div class="flex flex-wrap items-center gap-3 px-(--pad-panel) py-(--pad-row) text-sm text-ink-muted">
			The driver settings could not be read.
			<Button size="sm" onclick={loadTmcSettings}>Try again</Button>
		</div>
	{:else}
		<StepperDriverSettings
			loading={tmcLoading}
			bind:tmcIrun
			bind:tmcIhold
			bind:tmcMicrosteps
			bind:tmcStealthchop
			bind:tmcCoolstep
			bind:sgEnabled
			bind:sgThrs
			bind:sgTcoolthrs
			bind:stepperDirectionInverted
			cruiseSpeed={isChute ? chuteOperatingSpeed : null}
			{stallguardHref}
		/>
	{/if}
{/snippet}

{#snippet applyDriverButton()}
	<Button
		variant="primary"
		loading={tmcSaving}
		disabled={tmcLoading || tmcReadFailed}
		onclick={saveTmcSettings}
	>
		Apply the driver settings
	</Button>
{/snippet}

{#snippet endstopSettings()}
	<StepperEndstopSettings busy={loading || saving || homing || canceling} bind:endstopActiveHigh />
{/snippet}

{#snippet saveEndstopButton()}
	<Button
		variant="primary"
		loading={saving}
		disabled={loading || homing || canceling}
		onclick={saveEndstopSettings}
	>
		Save
	</Button>
{/snippet}

<div class="flex min-w-0 flex-col gap-(--gap-panels)">
	<Panel flush>
		<header
			class="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 px-(--pad-panel) pt-4 pb-3"
		>
			<div class="min-w-0">
				<div class="flex flex-wrap items-center gap-2">
					<h2 class="text-base font-semibold text-ink">{displayLabel}</h2>
					{#if stepperStopped === null}
						<Badge dot>Unknown</Badge>
					{:else if stepperStopped}
						<Badge dot>Stopped</Badge>
					{:else}
						<Badge tone="primary" dot>Moving</Badge>
					{/if}
					{#if isChute && chuteHomed !== null}
						<Badge tone={chuteHomed ? 'success' : 'warning'} dot>{chuteHomed ? 'Homed' : 'Not homed'}</Badge>
					{/if}
					{#if hasEndstop && endstopTriggered !== null}
						<Badge tone={endstopTriggered ? 'success' : 'neutral'}>
							{endstopTriggered ? 'Endstop triggered' : 'Endstop clear'}
						</Badge>
					{/if}
				</div>
				<p class="num mt-1 text-sm text-ink-muted">
					{#if isChute}
						Chute {formatNumber(chuteOutputAngle)}°, motor {formatNumber(chuteStepperDegrees)}°,
						{stepperMicrosteps ?? 'unknown'} microsteps
					{:else}
						At {formatNumber(currentPositionDegrees)}°, {stepperMicrosteps ?? 'unknown'} microsteps
					{/if}
				</p>
				{#if isChute}
					<p class="num text-sm text-ink-muted">
						Gear ratio {gearRatio.toFixed(2)}:1{chuteStepperDegrees !== null && chuteOutputAngle !== null
							? `: ${formatNumber(chuteStepperDegrees, 1)}° at the motor is ${formatNumber(chuteOutputAngle, 1)}° at the chute`
							: ''}
					</p>
				{/if}
				{#if hasEndstop}
					<p class="mt-1 text-sm text-ink-muted">
						Homing finds the endstop slowly. Cancel stops every stepper, in case the wrong motor
						moves.
					</p>
				{/if}
			</div>
			{#if hasEndstop}
				<StepperHoming
					{loading}
					{saving}
					{homing}
					{canceling}
					onHome={homeToEndstop}
					onCancel={cancelHoming}
				/>
			{/if}
		</header>

		{#if tmcStalled}
			<div class="px-(--pad-panel) pb-3">
				<Alert tone="danger" title="{displayLabel} stalled">
					Stall detection halted this motor. Clear the jam, then clear the stall. Its home position was
					dropped, so home it again before precise moves.
					{#snippet actions()}
						<Button variant="danger" size="sm" loading={tmcClearingStall} onclick={() => void clearStall()}>
							Clear the stall
						</Button>
					{/snippet}
				</Alert>
			</div>
		{/if}

		<div class="px-(--pad-panel) pb-(--pad-panel)">
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
			<!-- Always one line tall, so what a press says never moves what is below. -->
			<div class="mt-3 min-h-5 text-sm">{@render feedback('motor')}</div>
		</div>

		{#if !isChute}
			<div class="divide-y divide-line border-t border-line">
				<Disclosure title="Driver settings" help="Currents, microsteps, stall detection" bind:open={driverSettingsOpen}>
					{@render driverSettings()}
					<div class="flex items-center justify-end gap-3 px-(--pad-panel) py-(--pad-row)">
						<div class="mr-auto min-w-0 text-sm">{@render feedback('driver')}</div>
						{@render applyDriverButton()}
					</div>
					{#if tmcDrvStatus}<StepperDrvStatusGrid drvStatus={tmcDrvStatus} />{/if}
				</Disclosure>

				{#if hasEndstop}
					<Disclosure title="Endstop settings" bind:open={endstopSettingsOpen}>
						{@render endstopSettings()}
						<div class="flex items-center justify-end gap-3 px-(--pad-panel) pb-(--pad-row)">
							<div class="mr-auto min-w-0 text-sm">{@render feedback('endstop')}</div>
							{@render saveEndstopButton()}
						</div>
					</Disclosure>
				{/if}
			</div>
		{/if}
	</Panel>

	{#if isChute}
		<StepperChuteOperation
			{loading}
			{saving}
			{homing}
			{canceling}
			bind:chuteOperatingSpeed
			onSave={() => void saveChuteSettings('speed', 'Distributor operating speed saved.')}
			message={speedMessage}
		/>
		<StepperChuteStressTest operatingSpeed={chuteOperatingSpeed} />

		<Panel title="Driver settings" description="Currents, microsteps, stall detection." flush>
			{@render driverSettings()}
			{#if tmcDrvStatus}<StepperDrvStatusGrid drvStatus={tmcDrvStatus} />{/if}
			{#snippet footer()}
				<div class="mr-auto min-w-0 text-sm">{@render feedback('driver')}</div>
				{@render applyDriverButton()}
			{/snippet}
		</Panel>

		{#if hasEndstop}
			<Panel title="Endstop settings" flush>
				{@render endstopSettings()}
				{#snippet footer()}
					<div class="mr-auto min-w-0 text-sm">{@render feedback('endstop')}</div>
					{@render saveEndstopButton()}
				{/snippet}
			</Panel>
		{/if}
	{/if}
</div>
