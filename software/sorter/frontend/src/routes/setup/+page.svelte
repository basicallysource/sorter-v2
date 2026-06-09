<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount, untrack } from 'svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import SetupPictureSettingsModal from '$lib/components/setup/SetupPictureSettingsModal.svelte';
	import SetupServoOnboardingSection from '$lib/components/setup/SetupServoOnboardingSection.svelte';
	import SetupZoneEditorModal from '$lib/components/setup/SetupZoneEditorModal.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import SetupStepperNav from '$lib/components/setup/SetupStepperNav.svelte';
	import SetupNavFooter from '$lib/components/setup/SetupNavFooter.svelte';
	import IdentityStep from '$lib/components/setup/steps/IdentityStep.svelte';
	import ThemeStep from '$lib/components/setup/steps/ThemeStep.svelte';
	import DiscoveryStep from '$lib/components/setup/steps/DiscoveryStep.svelte';
	import CamerasStep from '$lib/components/setup/steps/CamerasStep.svelte';
	import MotionStep from '$lib/components/setup/steps/MotionStep.svelte';
	import CalibrationStep from '$lib/components/setup/steps/CalibrationStep.svelte';
	import HiveStep from '$lib/components/setup/steps/HiveStep.svelte';
	import AdvancedStep from '$lib/components/setup/steps/AdvancedStep.svelte';
	import {
		beginHiveLink,
		completeReturnedHiveLink,
		DEFAULT_HIVE_URL,
		type HiveLinkIntent
	} from '$lib/hive/link-flow';
	import { RefreshCcw } from 'lucide-svelte';
	import {
		loadStoredConfirmations as loadStoredConfirmationsFromStorage,
		persistConfirmations as persistConfirmationsToStorage,
		loadStoredVerificationState as loadStoredVerificationFromStorage,
		persistVerificationState as persistVerificationToStorage,
		loadStoredServoSource,
		persistServoSource,
		type PersistedServoSource
	} from '$lib/setup/wizard-storage';
	import {
		buildCameraChoices,
		parseCameraSource,
		sourceKey,
		type CameraChoice,
		type NetworkCamera,
		type UsbCamera
	} from '$lib/setup/camera-choices';
	import type {
		DiscoveredBoard,
		HiveConfigBackupSummary,
		HiveSetupTarget,
		StepperDirectionEntry,
		UsbDevice,
		WavesharePort,
		WizardSummary
	} from '$lib/setup/wizard-types';

	type WizardStepId =
		| 'identity'
		| 'theme'
		| 'discovery'
		| 'cameras'
		| 'motion'
		| 'calibration'
		| 'servos'
		| 'hive'
		| 'advanced';

	type WizardStepDefinition = {
		id: WizardStepId;
		title: string;
		kicker: string;
		description: string;
		requiresManualConfirm: boolean;
	};

	type WizardStepConfirmation = Partial<Record<WizardStepId, boolean>>;
	type IdentityMode = 'new' | 'restore';

	const machine = getMachineContext();
	const STEP_ORDER = [
		'c_channel_1',
		'c_channel_2',
		'c_channel_3',
		'c_channel_4',
		'carousel',
		'chute'
	];
	const ROLE_LABELS: Record<string, string> = {
		c_channel_2: 'C-Channel 2',
		c_channel_3: 'C-Channel 3',
		classification_channel: 'Classification C-Channel (C4)',
		carousel: 'Carousel',
		classification_top: 'Classification Top',
		classification_bottom: 'Classification Bottom'
	};
	const ROLE_DESCRIPTIONS: Record<string, string> = {
		c_channel_2:
			'Feeder path for the second C-channel. You can reuse the same camera for multiple areas.',
		c_channel_3:
			'Feeder path for the third C-channel. You can reuse the same camera for multiple areas.',
		classification_channel:
			'Classification C-channel platter. Use the dedicated C4 view when this machine runs the classification-channel setup.',
		carousel:
			'Carousel handoff area. This can share a camera with the feeder paths if the view covers it.',
		classification_top: 'Required top-down classification view.',
		classification_bottom: 'Optional crop for underside or second-pass classification.'
	};
	const OPTIONAL_ROLES = new Set(['classification_bottom']);
	const WIZARD_STEPS: WizardStepDefinition[] = [
		{
			id: 'identity',
			title: 'Machine Identity',
			kicker: 'Step 1',
			description:
				'Give the machine a friendly name so operators can identify it without the raw machine UUID.',
			requiresManualConfirm: false
		},
		{
			id: 'theme',
			title: 'Your Color',
			kicker: 'Step 2',
			description:
				'Pick the LEGO color that should drive the rest of the UI. Buttons, focus rings, and active highlights will all switch to your choice — change it any time from Settings.',
			requiresManualConfirm: false
		},
		{
			id: 'discovery',
			title: 'Controller Discovery',
			kicker: 'Step 3',
			description:
				'Review the USB controllers on this machine — we will use the ones identified as feeder, distribution, and Waveshare servo bus.',
			requiresManualConfirm: false
		},
		{
			id: 'motion',
			title: 'Motion Direction Check',
			kicker: 'Step 4',
			description:
				'Jog each axis a tiny amount and confirm whether it moved clockwise or counter-clockwise. The wizard will flip any reversed logical directions automatically.',
			requiresManualConfirm: true
		},
		{
			id: 'calibration',
			title: 'Endstops and Geometry',
			kicker: 'Step 5',
			description:
				'Verify each endstop polarity and the chute geometry. Homing itself runs later from the dashboard, right before a sorting run.',
			requiresManualConfirm: true
		},
		{
			id: 'servos',
			title: 'Servo Configuration',
			kicker: 'Step 6',
			description:
				'Discover the servos on the bus, calibrate and assign each one to a storage layer one-by-one.',
			requiresManualConfirm: true
		},
		{
			id: 'cameras',
			title: 'Cameras',
			kicker: 'Step 7',
			description:
				'Choose the camera layout, then assign a source to each machine area that needs coverage. The same camera can be reused for multiple areas.',
			requiresManualConfirm: false
		},
		{
			id: 'hive',
			title: 'Hive',
			kicker: 'Step 8',
			description:
				'Connect this sorter to the official Hive community platform so your samples and progress sync automatically. You can also skip this and set it up later from Settings.',
			requiresManualConfirm: true
		},
		{
			id: 'advanced',
			title: 'Setup Complete',
			kicker: 'Step 9',
			description:
				'Yay, the core setup is done. Next up: open the dashboard, home the machine if needed, and try a first run.',
			requiresManualConfirm: true
		}
	];
	const STEP_IDS = new Set<WizardStepId>(WIZARD_STEPS.map((step) => step.id));

	let loadedMachineKey = $state('');
	let wizard = $state<WizardSummary | null>(null);
	let loadingWizard = $state(false);
	let wizardError = $state<string | null>(null);

	let nicknameDraft = $state('');
	let savingName = $state(false);
	let nameError = $state<string | null>(null);
	let nameStatus = $state('');
	let identityMode = $state<IdentityMode>('new');
	let restoreBackups = $state<HiveConfigBackupSummary[]>([]);
	let restoreLoadingBackups = $state(false);
	let restoreSelectedVersion = $state<number | null>(null);
	let restoreIncludeCalibration = $state(false);
	let restoreApplying = $state(false);
	let restoreError = $state<string | null>(null);
	let restoreStatus = $state<string | null>(null);
	let restoreApplied = $state(false);

	let selectedLayout = $state<'default' | 'split_feeder'>('default');
	let savingLayout = $state(false);
	let layoutStatus = $state('');
	let layoutError = $state<string | null>(null);

	let usbCameras = $state<UsbCamera[]>([]);
	let networkCameras = $state<NetworkCamera[]>([]);
	let loadingCameras = $state(false);
	let cameraError = $state<string | null>(null);
	let cameraStatus = $state('');
	let savingAssignments = $state(false);
	let roleSelections = $state<Record<string, string>>({});
	let pictureSettingsRole = $state<string | null>(null);
	let zoneEditorRole = $state<string | null>(null);
	let reviewedZones = $state<Record<string, boolean>>({});
	let tunedPictures = $state<Record<string, boolean>>({});

	let hardwareState = $state('standby');
	let hardwareError = $state<string | null>(null);
	let homingStep = $state<string | null>(null);
	let homingSystem = $state(false);

	let stepperActionError = $state<string | null>(null);
	let stepperActionStatus = $state('');
	let stepperBusy = $state<Record<string, boolean>>({});
	let togglingStepper = $state<string | null>(null);
	let verifiedSteppers = $state<Record<string, boolean>>({});
	let showStepperWiringHelp = $state(false);

	// DEFAULT_HIVE_URL is the single source of truth in link-flow.ts
	// (https://hive.basically.website) — don't redeclare it here.

	let hiveLoading = $state(false);
	let hiveTargets = $state<HiveSetupTarget[]>([]);
	let hiveUrl = $state(DEFAULT_HIVE_URL);
	let hiveConnecting = $state(false);
	let hiveError = $state<string | null>(null);
	let hiveStatus = $state<string | null>(null);

	const officialSorthiveTarget = $derived(
		hiveTargets.find((target) => {
			try {
				return new URL(target.url).host === new URL(DEFAULT_HIVE_URL).host;
			} catch {
				return target.url.replace(/\/$/, '') === DEFAULT_HIVE_URL;
			}
		}) ?? null
	);
	const primaryHiveTarget = $derived(
		hiveTargets.find((target) => target.is_primary && target.enabled) ??
			hiveTargets.find((target) => target.enabled) ??
			null
	);

	let activeStepId = $state<WizardStepId>('identity');
	let stepConfirmations = $state<WizardStepConfirmation>({});
	let progressLoadedMachineId = $state('');
	let verificationLoadedMachineId = $state('');
	let calibrationStepRef = $state<CalibrationStep | null>(null);
	let storedServoSource = $state<PersistedServoSource | null>(null);
	let servoSourceLoadedMachineId = $state('');

	const discoveredWaveshareServos = $derived.by(() => {
		const devices = wizard?.discovery.usb_devices ?? [];
		const bus = devices.find(
			(device) => device.category === 'servo_bus' && (device.servo_count ?? 0) > 0
		);
		return bus ? (bus.servo_count ?? 0) : 0;
	});

	const discoveredServoSource = $derived<PersistedServoSource>(
		discoveredWaveshareServos > 0 ? 'waveshare' : 'pca'
	);

	const effectiveServoSource = $derived<PersistedServoSource>(
		storedServoSource ?? discoveredServoSource
	);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	async function responseErrorMessage(res: Response, fallback: string): Promise<string> {
		const text = await res.text();
		try {
			const body = JSON.parse(text);
			if (typeof body?.detail === 'string') return body.detail;
			if (typeof body?.error === 'string') return body.error;
		} catch {
			// Use text below.
		}
		return text || fallback;
	}

	function sleep(ms: number): Promise<void> {
		return new Promise((resolve) => setTimeout(resolve, ms));
	}

	function isLikelyRestartFetchError(error: unknown): boolean {
		const message =
			error instanceof Error
				? error.message
				: typeof error === 'string'
					? error
					: '';
		return /failed to fetch|networkerror|load failed|terminated|connection/i.test(message);
	}

	function currentMachineId(): string {
		return machine.machine?.identity?.machine_id ?? wizard?.machine.machine_id ?? '';
	}

	function loadStoredConfirmations(machineId: string) {
		stepConfirmations = loadStoredConfirmationsFromStorage<WizardStepId>(machineId);
		progressLoadedMachineId = machineId || '';
	}

	function persistConfirmations(machineId: string) {
		persistConfirmationsToStorage(machineId, stepConfirmations);
	}

	function loadStoredVerificationState(machineId: string) {
		const state = loadStoredVerificationFromStorage(machineId);
		reviewedZones = state.reviewedZones;
		tunedPictures = state.tunedPictures;
		verifiedSteppers = state.verifiedSteppers;
		verificationLoadedMachineId = machineId || '';
	}

	function loadServoSource(machineId: string) {
		storedServoSource = loadStoredServoSource(machineId);
		servoSourceLoadedMachineId = machineId || '';
	}

	function setServoSource(value: PersistedServoSource) {
		storedServoSource = value;
		const machineId = currentMachineId();
		if (machineId && servoSourceLoadedMachineId === machineId) {
			persistServoSource(machineId, value);
		}
	}

	function persistVerificationState(machineId: string) {
		persistVerificationToStorage(machineId, {
			reviewedZones,
			tunedPictures,
			verifiedSteppers
		});
	}

	function clearCameraVerification(role: string) {
		const nextReviewed = { ...reviewedZones };
		delete nextReviewed[role];
		reviewedZones = nextReviewed;

		const nextTuned = { ...tunedPictures };
		delete nextTuned[role];
		tunedPictures = nextTuned;
	}

	function clearAllCameraVerification() {
		reviewedZones = {};
		tunedPictures = {};
	}

	function clearManualConfirmations(stepIds: WizardStepId[]) {
		const next = { ...stepConfirmations };
		for (const stepId of stepIds) {
			delete next[stepId];
		}
		stepConfirmations = next;
	}

	function stepperEntries(): StepperDirectionEntry[] {
		const entries = wizard?.config.stepper_directions ?? [];
		return [...entries].sort((a, b) => STEP_ORDER.indexOf(a.name) - STEP_ORDER.indexOf(b.name));
	}

	function cameraRolesForLayout(): string[] {
		const setup = wizard?.config.machine_setup;
		const auxiliaryRole = setup?.uses_classification_channel ? 'classification_channel' : 'carousel';
		const roles = ['c_channel_2', 'c_channel_3', auxiliaryRole];
		if (setup?.uses_classification_chamber ?? true) {
			roles.push('classification_top', 'classification_bottom');
		}
		return roles;
	}

	function parseRouteStep(step: string | null): WizardStepId | null {
		if (!step || !STEP_IDS.has(step as WizardStepId)) return null;
		return step as WizardStepId;
	}

	function stepHref(stepId: WizardStepId): string {
		const params = new URLSearchParams(page.url.searchParams);
		params.set('step', stepId);
		const query = params.toString();
		return query ? `${page.url.pathname}?${query}` : page.url.pathname;
	}

	async function navigateToStep(stepId: WizardStepId, replaceState = false) {
		const href = stepHref(stepId);
		if (`${page.url.pathname}${page.url.search}` === href) return;
		await goto(href, {
			replaceState,
			noScroll: true,
			keepFocus: true
		});
	}

	function cameraChoices(): CameraChoice[] {
		return buildCameraChoices(usbCameras, networkCameras, roleSelections, currentBackendBaseUrl());
	}

	function selectedCameraLabel(key: string | undefined): string {
		const choice = cameraChoices().find((entry) => entry.key === (key ?? '__none__'));
		return choice?.label ?? 'No camera selected';
	}

	function roleHasCamera(role: string): boolean {
		return parseCameraSource(roleSelections[role] ?? '__none__') !== null;
	}

	function openPictureSettings(role: string) {
		if (!roleHasCamera(role)) return;
		pictureSettingsRole = role;
	}

	function closePictureSettings() {
		pictureSettingsRole = null;
	}

	function openZoneEditor(role: string) {
		if (!roleHasCamera(role)) return;
		zoneEditorRole = role;
	}

	function closeZoneEditor() {
		zoneEditorRole = null;
	}

	function markZoneReviewed(role: string) {
		reviewedZones = { ...reviewedZones, [role]: true };
	}

	function markPictureTuned(role: string) {
		tunedPictures = { ...tunedPictures, [role]: true };
	}

	function stepStatus(stepId: WizardStepId): 'current' | 'done' | 'locked' | 'ready' {
		if (activeStepId === stepId) return 'current';
		if (isStepComplete(stepId)) return 'done';
		if (!isStepUnlocked(stepId)) return 'locked';
		return 'ready';
	}

	function stepDefinition(stepId: WizardStepId): WizardStepDefinition {
		return WIZARD_STEPS.find((step) => step.id === stepId) ?? WIZARD_STEPS[0];
	}

	function stepIndex(stepId: WizardStepId): number {
		return WIZARD_STEPS.findIndex((step) => step.id === stepId);
	}

	function currentStepNumber(): number {
		return stepIndex(activeStepId) + 1;
	}

	function currentStep(): WizardStepDefinition {
		return stepDefinition(activeStepId);
	}

	function isStepComplete(stepId: WizardStepId): boolean {
		switch (stepId) {
			case 'identity':
				if (identityMode === 'restore') {
					return restoreApplied || Boolean(wizard?.readiness.machine_named);
				}
				return Boolean(wizard?.readiness.machine_named);
			case 'theme':
				return true;
			case 'discovery':
				return Boolean(wizard?.readiness.boards_detected);
			case 'cameras':
				return (
					Boolean(wizard?.readiness.camera_layout_selected) &&
					Boolean(wizard?.readiness.cameras_assigned)
				);
			case 'motion':
				return Boolean(stepConfirmations.motion);
			case 'calibration':
				return Boolean(stepConfirmations.calibration);
			case 'servos':
				return Boolean(wizard?.readiness.servo_configured) && Boolean(stepConfirmations.servos);
			case 'hive':
				return Boolean(stepConfirmations.hive) || officialSorthiveTarget !== null;
			case 'advanced':
				return Boolean(stepConfirmations.advanced);
		}
	}

	function isStepUnlocked(stepId: WizardStepId): boolean {
		const index = stepIndex(stepId);
		if (index <= 0) return true;
		for (const previous of WIZARD_STEPS.slice(0, index)) {
			if (!isStepComplete(previous.id)) return false;
		}
		return true;
	}

	function canOpenStep(stepId: WizardStepId): boolean {
		return isStepUnlocked(stepId) || isStepComplete(stepId);
	}

	function currentStepLocked(): boolean {
		return !canOpenStep(activeStepId) && !isStepComplete(activeStepId);
	}

	function setActiveStep(stepId: string) {
		const id = stepId as WizardStepId;
		if (!canOpenStep(id)) return;
		void navigateToStep(id);
	}

	function goToPreviousStep() {
		const index = stepIndex(activeStepId);
		if (index <= 0) return;
		void navigateToStep(WIZARD_STEPS[index - 1].id);
	}

	function goToNextStep() {
		const index = stepIndex(activeStepId);
		if (index < 0 || index >= WIZARD_STEPS.length - 1) return;
		const nextStepId = WIZARD_STEPS[index + 1].id;
		void navigateToStep(nextStepId);
	}

	function manualConfirmLabel(stepId: WizardStepId): string {
		switch (stepId) {
			case 'motion':
				return 'Directions look correct';
			case 'calibration':
				return 'Endstops and geometry look correct';
			case 'servos':
				return 'Servo setup looks correct';
			case 'hive':
				return 'Continue';
			case 'advanced':
				return 'Open Dashboard';
			default:
				return 'Continue';
		}
	}

	function manualConfirmEnabled(stepId: WizardStepId): boolean {
		switch (stepId) {
			case 'motion':
				return hardwareState === 'initialized' || hardwareState === 'ready';
			case 'calibration':
				return hardwareState === 'initialized' || hardwareState === 'ready';
			case 'servos':
				return Boolean(wizard?.readiness.servo_configured);
			case 'hive':
				return isStepComplete('hive');
			case 'advanced':
				return true;
			default:
				return true;
		}
	}

	async function finishSetup() {
		stepConfirmations = {
			...stepConfirmations,
			advanced: true
		};
		const machineId = currentMachineId();
		if (machineId && progressLoadedMachineId === machineId) {
			persistConfirmations(machineId);
		}
		await goto('/', {
			noScroll: true,
			keepFocus: true
		});
	}

	const STEP_BLOCKERS: Record<string, () => string | null> = {
		identity: () => {
			if (identityMode === 'restore') {
				if (hiveConnecting) return 'Finish the Hive connection first';
				if (restoreApplying) return 'Restore is running...';
				if (!restoreApplied && !wizard?.readiness.machine_named)
					return 'Connect to Hive and restore a machine backup to continue';
				return null;
			}
			if (nicknameDraft.trim().length === 0) return 'Enter a machine name to continue';
			if (savingName) return 'Saving name…';
			return null;
		},
		discovery: () => {
			if (!wizard?.readiness.boards_detected) return 'Waiting for controller boards to be detected';
			return null;
		},
		motion: () => {
			if (hardwareState !== 'initialized' && hardwareState !== 'ready')
				return 'Hardware must be initialized before continuing';
			return null;
		},
		calibration: () => {
			if (hardwareState !== 'initialized' && hardwareState !== 'ready')
				return 'Hardware must be initialized before continuing';
			return null;
		},
		cameras: () => {
			if (!wizard?.readiness.camera_layout_selected) return 'Select a camera layout to continue';
			if (!wizard?.readiness.cameras_assigned) return 'Assign cameras to all required areas';
			return null;
		},
		servos: () => {
			if (!wizard?.readiness.servo_configured) return 'Configure servos before continuing';
			return null;
		}
	};

	function stepBlockerReason(): string | null {
		if (currentStepLocked()) return 'Complete previous steps first';
		return STEP_BLOCKERS[activeStepId]?.() ?? null;
	}

	function canAdvanceCurrentStep(): boolean {
		if (activeStepId === 'identity') {
			if (identityMode === 'restore') {
				return !hiveConnecting && !restoreApplying && (restoreApplied || Boolean(wizard?.readiness.machine_named));
			}
			return !savingName && nicknameDraft.trim().length > 0;
		}
		if (currentStep().requiresManualConfirm) {
			return manualConfirmEnabled(activeStepId);
		}
		return isStepComplete(activeStepId);
	}

	async function handleContinue() {
		if (activeStepId === 'identity') {
			if (identityMode === 'restore') {
				await loadWizard();
				await navigateToStep('discovery');
				return;
			}
			await saveMachineName();
			return;
		}
		if (activeStepId === 'motion') {
			stepConfirmations = { ...stepConfirmations, motion: true };
		}
		if (activeStepId === 'calibration') {
			if (calibrationStepRef) {
				const ok = await calibrationStepRef.persistPendingSettings();
				if (!ok) return;
			}
			stepConfirmations = { ...stepConfirmations, calibration: true };
		}
		if (activeStepId === 'servos') {
			stepConfirmations = { ...stepConfirmations, servos: true };
		}
		goToNextStep();
	}

	async function fetchWizardSummary(): Promise<WizardSummary> {
		const res = await fetch(`${currentBackendBaseUrl()}/api/setup-wizard`, { cache: 'no-store' });
		if (!res.ok) throw new Error(await res.text());
		return (await res.json()) as WizardSummary;
	}

	function applyWizardSummary(payload: WizardSummary) {
		wizard = payload;
		hardwareState = payload.hardware.state;
		hardwareError = payload.hardware.error;
		homingStep = payload.hardware.homing_step;
		nicknameDraft = payload.machine.nickname ?? '';
		const configuredLayout = payload.config.camera_assignments.layout;
		selectedLayout =
			configuredLayout === 'split_feeder'
				? 'split_feeder'
				: configuredLayout === 'default'
					? 'default'
					: payload.discovery.recommended_camera_layout;

		const nextSelections: Record<string, string> = {};
		for (const role of Object.keys(payload.config.camera_assignments)) {
			if (role === 'layout') continue;
			nextSelections[role] = sourceKey(payload.config.camera_assignments[role]);
		}
		roleSelections = nextSelections;
	}

	async function loadWizard() {
		loadingWizard = true;
		wizardError = null;
		try {
			applyWizardSummary(await fetchWizardSummary());
		} catch (e: any) {
			wizardError = e.message ?? 'Failed to load setup wizard state';
		} finally {
			loadingWizard = false;
		}
	}

	async function waitForBackendAfterRestore() {
		const baseUrl = currentBackendBaseUrl();
		const deadline = Date.now() + 45_000;
		let lastError: unknown = null;

		while (Date.now() < deadline) {
			try {
				const res = await fetch(`${baseUrl}/health`, { cache: 'no-store' });
				if (res.ok) break;
			} catch (e) {
				lastError = e;
			}
			await sleep(750);
		}

		for (let attempt = 0; attempt < 30; attempt += 1) {
			try {
				applyWizardSummary(await fetchWizardSummary());
				wizardError = null;
				return;
			} catch (e) {
				lastError = e;
				await sleep(750);
			}
		}

		throw new Error(
			lastError instanceof Error
				? lastError.message
				: 'Backend did not come back after restore.'
		);
	}

	async function loadSorthiveConfig() {
		hiveLoading = true;
		hiveError = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			const rawTargets = Array.isArray(payload?.targets) ? payload.targets : [];
			hiveTargets = rawTargets.map((entry: any, index: number) => ({
				id: typeof entry?.id === 'string' && entry.id.trim() ? entry.id : `target-${index + 1}`,
				name:
					typeof entry?.name === 'string' && entry.name.trim()
						? entry.name
						: typeof entry?.url === 'string'
							? entry.url
							: `Hive ${index + 1}`,
				url: typeof entry?.url === 'string' ? entry.url : '',
				machine_id: typeof entry?.machine_id === 'string' ? entry.machine_id : null,
				enabled: Boolean(entry?.enabled),
				is_primary: Boolean(entry?.is_primary)
			})) satisfies HiveSetupTarget[];
		} catch (e: any) {
			hiveError = e.message ?? 'Failed to load Hive configuration.';
		} finally {
			hiveLoading = false;
		}
	}

	async function loadConfigBackups() {
		restoreLoadingBackups = true;
		restoreError = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hive/config-backups`);
			if (!res.ok) {
				throw new Error(await responseErrorMessage(res, 'Failed to load config backups.'));
			}
			const payload = await res.json();
			const versions = Array.isArray(payload?.versions) ? payload.versions : [];
			restoreBackups = versions.map((entry: any) => ({
				id: String(entry.id ?? `${entry.version ?? ''}`),
				version: Number(entry.version ?? 0),
				content_hash: String(entry.content_hash ?? ''),
				trigger: String(entry.trigger ?? 'config_change'),
				created_at: String(entry.created_at ?? '')
			})) satisfies HiveConfigBackupSummary[];
			const latest = restoreBackups[0]?.version ?? null;
			if (
				restoreSelectedVersion === null ||
				!restoreBackups.some((backup) => backup.version === restoreSelectedVersion)
			) {
				restoreSelectedVersion = latest;
			}
			if (restoreBackups.length === 0) {
				restoreStatus = 'No Hive backups found for this machine profile yet.';
			}
		} catch (e: any) {
			restoreError = e?.message ?? 'Failed to load config backups.';
		} finally {
			restoreLoadingBackups = false;
		}
	}

	async function applySelectedConfigBackup() {
		if (restoreSelectedVersion === null) return;
		restoreApplying = true;
		restoreError = null;
		restoreStatus = null;
		try {
			let responseInterruptedByRestart = false;
			try {
				const res = await fetch(`${currentBackendBaseUrl()}/api/hive/config-backup/restore`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						version: restoreSelectedVersion,
						include_calibration: restoreIncludeCalibration
					})
				});
				if (!res.ok) {
					throw new Error(await responseErrorMessage(res, 'Restore failed.'));
				}
			} catch (e) {
				if (!isLikelyRestartFetchError(e)) throw e;
				responseInterruptedByRestart = true;
			}
			restoreApplied = true;
			restoreStatus = responseInterruptedByRestart
				? 'Restore request reached the backend. Waiting for it to restart with the restored settings...'
				: 'Restore applied. The backend is restarting with the restored settings...';
			stepConfirmations = {
				...stepConfirmations,
				hive: true,
				motion: false,
				calibration: false,
				servos: false,
				cameras: false
			};
			const machineId = currentMachineId();
			if (machineId && progressLoadedMachineId === machineId) {
				persistConfirmations(machineId);
			}
			await waitForBackendAfterRestore();
			restoreStatus = 'Restore applied. Review the hardware steps before continuing.';
			await loadCameraInventory();
		} catch (e: any) {
			restoreError =
				e?.message === 'Failed to fetch'
					? 'Restore is still waiting for the backend to come back. Refresh the setup page if this does not clear in a moment.'
					: e?.message ?? 'Restore failed.';
		} finally {
			restoreApplying = false;
		}
	}

	function connectToSorthive(intent: HiveLinkIntent = 'connect') {
		const url = (hiveUrl.trim() || DEFAULT_HIVE_URL).trim();
		if (!url) return;
		hiveConnecting = true;
		hiveError = null;
		hiveStatus = null;
		restoreError = null;
		restoreStatus = null;
		if (intent === 'restore') {
			restoreBackups = [];
			restoreSelectedVersion = null;
			restoreApplied = false;
		}
		const machineName =
			(wizard?.machine.nickname ?? '').trim() ||
			nicknameDraft.trim() ||
			(wizard?.machine.machine_id ?? '');
		try {
			beginHiveLink({
				hiveUrl: url,
				targetName: undefined,
				machineName: machineName || undefined,
				intent,
				// Bring the user back to the same setup step so the
				// returned-link handler at mount can finish the pairing.
				returnPath:
					intent === 'restore'
						? `${window.location.pathname}?${new URLSearchParams({ step: 'identity' }).toString()}`
						: window.location.pathname + window.location.search
			});
			// beginHiveLink redirects; if it returns we never got there.
		} catch (e: any) {
			hiveError = e?.message ?? 'Could not start the Hive link flow.';
			hiveConnecting = false;
		}
	}

	async function handleReturnedSorthiveLink() {
		try {
			const result = await completeReturnedHiveLink(currentBackendBaseUrl());
			if (!result.completed) return;
			if (result.intent === 'restore') {
				identityMode = 'restore';
				restoreStatus =
					result.message ?? 'Connected to Hive. Choose a backup version to restore.';
			}
			hiveStatus =
				result.message ?? 'Connected to Hive. Sample sync will resume in the background.';
			stepConfirmations = { ...stepConfirmations, hive: true };
			const machineId = currentMachineId();
			if (machineId && progressLoadedMachineId === machineId) {
				persistConfirmations(machineId);
			}
			await loadSorthiveConfig();
			if (result.intent === 'restore') {
				await loadConfigBackups();
			}
		} catch (e: any) {
			hiveError = e?.message ?? 'Hive link could not be completed.';
			restoreError = e?.message ?? 'Hive link could not be completed.';
		} finally {
			hiveConnecting = false;
		}
	}

	function skipSorthive() {
		hiveError = null;
		hiveStatus = 'Skipped for now. You can connect any time from Settings › Hive.';
		stepConfirmations = { ...stepConfirmations, hive: true };
		const machineId = currentMachineId();
		if (machineId && progressLoadedMachineId === machineId) {
			persistConfirmations(machineId);
		}
		goToNextStep();
	}

	async function loadCameraInventory() {
		loadingCameras = true;
		cameraError = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/cameras/list`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			usbCameras = Array.isArray(payload?.usb)
				? payload.usb.filter((camera: UsbCamera) => camera.index >= 0)
				: [];
			networkCameras = Array.isArray(payload?.network) ? payload.network : [];
		} catch (e: any) {
			cameraError = e.message ?? 'Failed to load camera inventory';
		} finally {
			loadingCameras = false;
		}
	}

	$effect(() => {
		const ws = machine.machine?.systemStatus;
		if (!ws) return;
		const nextState = ws.hardware_state ?? 'standby';
		const previousState = hardwareState;
		hardwareState = nextState;
		hardwareError = ws.hardware_error ?? null;
		homingStep = ws.homing_step ?? null;
		if (nextState !== previousState) {
			void loadWizard();
		}
	});

	async function saveMachineName() {
		savingName = true;
		nameError = null;
		nameStatus = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/machine-identity`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					nickname: nicknameDraft.trim() || null
				})
			});
			if (!res.ok) throw new Error(await res.text());
			nameStatus = 'Machine name saved.';
			await loadWizard();
			await navigateToStep('discovery');
		} catch (e: any) {
			nameError = e.message ?? 'Failed to save machine name';
		} finally {
			savingName = false;
		}
	}

	async function saveCameraAssignments() {
		savingAssignments = true;
		cameraError = null;
		cameraStatus = '';
		try {
			const changedRoles = cameraRolesForLayout().filter(
				(role) =>
					sourceKey(wizard?.config.camera_assignments[role] ?? null) !==
					(roleSelections[role] ?? '__none__')
			);
			const payload: Record<string, number | string | null> = { layout: selectedLayout };
			for (const role of cameraRolesForLayout()) {
				payload[role] = parseCameraSource(roleSelections[role] ?? '__none__');
			}

			const res = await fetch(`${currentBackendBaseUrl()}/api/cameras/assign`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload)
			});
			if (!res.ok) throw new Error(await res.text());
			clearManualConfirmations(['motion', 'calibration', 'servos', 'advanced']);
			for (const role of changedRoles) {
				clearCameraVerification(role);
			}
			cameraStatus = 'Camera assignments saved.';
			await loadWizard();
			await navigateToStep('motion');
		} catch (e: any) {
			cameraError = e.message ?? 'Failed to save camera assignments';
		} finally {
			savingAssignments = false;
		}
	}

	async function initializeSteppers() {
		homingSystem = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/initialize`, {
				method: 'POST'
			});
			if (!res.ok) throw new Error(await res.text());
		} catch (e: any) {
			hardwareError = e.message ?? 'Failed to power on steppers';
		} finally {
			homingSystem = false;
		}
	}

	async function pulseStepper(stepperName: string, direction: 'cw' | 'ccw') {
		const key = `${stepperName}:${direction}`;
		stepperBusy = { ...stepperBusy, [key]: true };
		stepperActionError = null;
		stepperActionStatus = '';
		try {
			const params = new URLSearchParams({
				stepper: stepperName,
				direction,
				duration_s: '0.25',
				speed: '600'
			});
			const res = await fetch(`${currentBackendBaseUrl()}/stepper/pulse?${params.toString()}`, {
				method: 'POST'
			});
			if (!res.ok) throw new Error(await res.text());
			stepConfirmations = { ...stepConfirmations, motion: false };
			stepperActionStatus = `${stepperName} jogged ${direction.toUpperCase()}.`;
		} catch (e: any) {
			stepperActionError = e.message ?? `Failed to pulse ${stepperName}`;
		} finally {
			stepperBusy = { ...stepperBusy, [key]: false };
		}
	}

	async function setStepperInverted(entry: StepperDirectionEntry, inverted: boolean) {
		const res = await fetch(
			`${currentBackendBaseUrl()}/api/setup-wizard/stepper-directions/${entry.name}`,
			{
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ inverted })
			}
		);
		if (!res.ok) throw new Error(await res.text());
	}

	async function recordObservedDirection(entry: StepperDirectionEntry, observed: 'cw' | 'ccw') {
		const desiredInverted = observed === 'cw' ? entry.inverted : !entry.inverted;
		togglingStepper = entry.name;
		stepperActionError = null;
		stepperActionStatus = '';
		try {
			if (desiredInverted !== entry.inverted) {
				await setStepperInverted(entry, desiredInverted);
			}
			verifiedSteppers = { ...verifiedSteppers, [entry.name]: true };
			stepperActionStatus =
				observed === 'cw'
					? `${entry.label} confirmed clockwise${desiredInverted ? ' (inverted in software)' : ''}.`
					: `${entry.label} now inverted in software (you saw counterclockwise).`;
			await loadWizard();
		} catch (e: any) {
			stepperActionError = e.message ?? `Failed to update ${entry.label}`;
		} finally {
			togglingStepper = null;
		}
	}

	async function handleServoSaved() {
		clearManualConfirmations(['servos', 'advanced']);
		await loadWizard();
	}

	function handleRoleSelection(role: string, key: string) {
		roleSelections = {
			...roleSelections,
			[role]: key
		};
	}

	const machineDisplayName = $derived(
		(wizard?.machine.nickname ?? '').trim() ||
			nicknameDraft.trim() ||
			wizard?.machine.machine_id ||
			'Unnamed sorter'
	);

	$effect(() => {
		const machineId = currentMachineId();
		if (!machineId || progressLoadedMachineId !== machineId) return;
		persistConfirmations(machineId);
	});

	$effect(() => {
		const machineId = currentMachineId();
		if (!machineId || verificationLoadedMachineId !== machineId) return;
		persistVerificationState(machineId);
	});

	$effect(() => {
		const routeStep = parseRouteStep(page.url.searchParams.get('step'));
		activeStepId = routeStep ?? 'identity';
		if (routeStep === null) {
			void navigateToStep('identity', true);
		}
	});

	$effect(() => {
		const machineId = currentMachineId();
		if (!machineId || machineId === loadedMachineKey) return;
		loadedMachineKey = machineId;
		loadStoredConfirmations(machineId);
		loadStoredVerificationState(machineId);
		loadServoSource(machineId);
		void loadWizard();
		void loadCameraInventory();
	});

	$effect(() => {
		if (activeStepId !== 'motion' && activeStepId !== 'calibration') return;
		if (homingSystem) return;
		if (hardwareState === 'standby') {
			void initializeSteppers();
		}
	});

	$effect(() => {
		if (activeStepId !== 'hive') return;
		untrack(() => {
			void loadSorthiveConfig();
		});
	});

	$effect(() => {
		if (activeStepId !== 'identity' || identityMode !== 'restore') return;
		if (hiveLoading || hiveTargets.length > 0 || hiveError) return;
		untrack(() => {
			void loadSorthiveConfig();
		});
	});

	$effect(() => {
		if (activeStepId !== 'identity' || identityMode !== 'restore' || !primaryHiveTarget) return;
		if (restoreLoadingBackups || restoreBackups.length > 0 || restoreError) return;
		untrack(() => {
			void loadConfigBackups();
		});
	});

	onMount(() => {
		const machineId = currentMachineId();
		if (machineId) {
			loadStoredConfirmations(machineId);
			loadStoredVerificationState(machineId);
			loadServoSource(machineId);
		}
		void loadWizard();
		void loadCameraInventory();
		// If the user just came back from Hive with a pairing token in
		// the URL hash, finish the link before they touch anything else.
		void handleReturnedSorthiveLink();
	});
</script>

<div class="min-h-screen overflow-x-hidden bg-bg">
	<AppHeader />
	<div class="mx-auto flex max-w-[1500px] flex-col gap-6 px-4 py-6 sm:px-6">
		{#if !machine.machine}
			<section class="setup-card-shell border border-border bg-surface p-6">
				<h1 class="text-2xl font-semibold text-text">Setup Wizard</h1>
				<p class="mt-2 max-w-2xl text-sm text-text-muted">
					Select or connect a machine first. After that, this wizard will walk through the setup one
					step at a time instead of dropping the whole config surface on one page.
				</p>
			</section>
		{:else}
			{#if wizardError}
				<div class="border border-danger bg-danger/10 px-4 py-3 text-sm text-danger">
					{wizardError}
				</div>
			{/if}

			<div class="flex flex-col gap-6">
				<section class="setup-card-shell overflow-hidden border border-border">
					<div class="setup-card-body px-6 py-6">
						<SetupStepperNav
							steps={WIZARD_STEPS}
							getStatus={(id) => stepStatus(id as WizardStepId)}
							canOpenStep={(id) => canOpenStep(id as WizardStepId)}
							onSelect={setActiveStep}
						/>
					</div>
				</section>

				<SectionCard
					title={currentStep().title}
					description={currentStep().description}
					rootClass="setup-card-shell"
					headerClass="setup-card-header"
					bodyClass="setup-card-body"
					on:refresh-cameras={loadCameraInventory}
				>
					{#if !wizard && loadingWizard}
						<div class="setup-panel px-4 py-4 text-sm text-text-muted">
							Checking the current machine configuration and connected hardware…
						</div>
					{:else if !wizard}
						<div class="border border-danger bg-danger/10 px-4 py-3 text-sm text-danger">
							{wizardError ?? 'The backend did not return setup data.'}
						</div>
						<div class="mt-4 flex flex-wrap gap-3">
							<button
								onclick={loadWizard}
								disabled={loadingWizard}
								class="setup-button-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
							>
								<RefreshCcw size={14} class={loadingWizard ? 'animate-spin' : ''} />
								Try Again
							</button>
						</div>
					{:else if currentStepLocked()}
						<div class="setup-panel px-4 py-4 text-sm text-text-muted">
							This step keeps its own URL at
							<span class="font-mono text-text">{stepHref(activeStepId)}</span>, but it stays locked
							until the previous steps are complete.
						</div>
					{:else if activeStepId === 'identity'}
						<IdentityStep
							machineId={wizard?.machine.machine_id ?? machine.machine.identity?.machine_id ?? ''}
							bind:mode={identityMode}
							bind:nicknameDraft
							{nameError}
							{nameStatus}
							officialHiveTarget={primaryHiveTarget}
							defaultHiveUrl={DEFAULT_HIVE_URL}
							bind:hiveUrl
							{hiveConnecting}
							{restoreBackups}
							{restoreLoadingBackups}
							bind:restoreSelectedVersion
							bind:restoreIncludeCalibration
							{restoreApplying}
							{restoreError}
							{restoreStatus}
							{restoreApplied}
							onConnectRestore={() => connectToSorthive('restore')}
							onRefreshBackups={loadConfigBackups}
							onRestore={applySelectedConfigBackup}
						/>
					{:else if activeStepId === 'theme'}
						<ThemeStep />
					{:else if activeStepId === 'discovery'}
						<DiscoveryStep
							usbDevices={wizard?.discovery.usb_devices ?? []}
							issues={wizard?.discovery.issues ?? []}
							{loadingWizard}
							onRescan={loadWizard}
						/>
					{:else if activeStepId === 'cameras'}
						<CamerasStep
							cameraRoles={cameraRolesForLayout()}
							roleLabels={ROLE_LABELS}
							roleDescriptions={ROLE_DESCRIPTIONS}
							optionalRoles={OPTIONAL_ROLES}
							{roleSelections}
							{reviewedZones}
							{tunedPictures}
							cameraChoices={cameraChoices()}
							{selectedCameraLabel}
							{savingAssignments}
							{savingLayout}
							{cameraError}
							{cameraStatus}
							onSelect={handleRoleSelection}
							onOpenPictureSettings={openPictureSettings}
							onOpenZoneEditor={openZoneEditor}
							onSave={saveCameraAssignments}
						/>
					{:else if activeStepId === 'motion'}
						<MotionStep
							{hardwareState}
							{hardwareError}
							{homingStep}
							{homingSystem}
							stepperEntries={stepperEntries()}
							{stepperBusy}
							{togglingStepper}
							{verifiedSteppers}
							{stepperActionError}
							boards={wizard?.discovery.boards ?? []}
							bind:showStepperWiringHelp
							onInitialize={initializeSteppers}
							onPulse={pulseStepper}
							onRecordObservedDirection={recordObservedDirection}
						/>
					{:else if activeStepId === 'calibration'}
						<CalibrationStep bind:this={calibrationStepRef} />
					{:else if activeStepId === 'servos'}
						<SetupServoOnboardingSection
							servoSource={effectiveServoSource}
							discoveredServoSource={discoveredServoSource}
							discoveredWaveshareServos={discoveredWaveshareServos}
							onSaved={handleServoSaved}
							onSourceChange={setServoSource}
						/>
					{:else if activeStepId === 'hive'}
						<HiveStep
							{hiveLoading}
							officialHiveTarget={officialSorthiveTarget}
							defaultHiveUrl={DEFAULT_HIVE_URL}
							bind:hiveUrl
							{hiveConnecting}
							{hiveError}
							{hiveStatus}
							{machineDisplayName}
							onConnect={connectToSorthive}
							onSkip={skipSorthive}
						/>
					{:else if activeStepId === 'advanced'}
						<AdvancedStep />
					{/if}

					{@const isAdvanced = activeStepId === 'advanced'}
					{@const continueDisabled =
						currentStepLocked() ||
						!canAdvanceCurrentStep() ||
						(currentStep().requiresManualConfirm && !manualConfirmEnabled(activeStepId))}
					{@const continueLabel =
						activeStepId === 'identity' && savingName
							? 'Saving...'
							: currentStep().requiresManualConfirm
								? manualConfirmLabel(activeStepId)
								: 'Continue'}
					<SetupNavFooter
						blockerReason={stepBlockerReason()}
						showBack={currentStepNumber() > 1}
						showFinish={isAdvanced && currentStep().requiresManualConfirm && !currentStepLocked()}
						showContinue={!isAdvanced}
						{continueDisabled}
						{continueLabel}
						finishDisabled={!manualConfirmEnabled(activeStepId) || isStepComplete(activeStepId)}
						finishLabel={manualConfirmLabel(activeStepId)}
						onBack={goToPreviousStep}
						onFinish={finishSetup}
						onContinue={handleContinue}
					/>
				</SectionCard>
			</div>
		{/if}

		<Modal
			open={pictureSettingsRole !== null}
			title="Picture Settings"
			wide={true}
			on:close={closePictureSettings}
		>
			{#if pictureSettingsRole}
				<SetupPictureSettingsModal
					role={pictureSettingsRole as any}
					label={ROLE_LABELS[pictureSettingsRole] ?? pictureSettingsRole}
					hasCamera={roleHasCamera(pictureSettingsRole)}
					source={parseCameraSource(roleSelections[pictureSettingsRole] ?? '__none__')}
					backendBaseUrl={currentBackendBaseUrl()}
					on:saved={() => {
						const role = pictureSettingsRole;
						if (!role) return;
						markPictureTuned(role);
						cameraStatus = `${ROLE_LABELS[role] ?? role} picture settings saved.`;
						closePictureSettings();
					}}
				/>
			{/if}
		</Modal>

		<Modal open={zoneEditorRole !== null} title="Edit Zone" wide={true} on:close={closeZoneEditor}>
			{#if zoneEditorRole}
				<SetupZoneEditorModal
					role={zoneEditorRole as any}
					on:saved={() => {
						const role = zoneEditorRole;
						if (!role) return;
						markZoneReviewed(role);
						cameraStatus = `${ROLE_LABELS[role] ?? role} zone saved.`;
						closeZoneEditor();
					}}
				/>
			{/if}
		</Modal>
	</div>
</div>
