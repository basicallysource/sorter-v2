<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount, untrack } from 'svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { backendHttpBaseUrl, backendWsBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import SetupHomingSection from '$lib/components/setup/SetupHomingSection.svelte';
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
	import HiveStep from '$lib/components/setup/steps/HiveStep.svelte';
	import AdvancedStep from '$lib/components/setup/steps/AdvancedStep.svelte';
	import { RefreshCcw } from 'lucide-svelte';
	import {
		beginHiveLink,
		completeReturnedHiveLink,
		DEFAULT_HIVE_URL,
		normalizeHiveBaseUrl
	} from '$lib/hive/link-flow';
	import {
		loadStoredConfirmations as loadStoredConfirmationsFromStorage,
		persistConfirmations as persistConfirmationsToStorage,
		loadStoredVerificationState as loadStoredVerificationFromStorage,
		persistVerificationState as persistVerificationToStorage
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
		| 'homing'
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

	const machine = getMachineContext();
	const STEP_ORDER = ['c_channel_1', 'c_channel_2', 'c_channel_3', 'carousel', 'chute'];
	const ROLE_LABELS: Record<string, string> = {
		c_channel_2: 'C-Channel 2',
		c_channel_3: 'C-Channel 3',
		carousel: 'Carousel',
		classification_channel: 'Classification C-Channel (C4)',
		classification_top: 'Classification Top',
		classification_bottom: 'Classification Bottom'
	};
	const ROLE_DESCRIPTIONS: Record<string, string> = {
		c_channel_2: 'Feeder path for the second C-channel. You can reuse the same camera for multiple areas.',
		c_channel_3: 'Feeder path for the third C-channel. You can reuse the same camera for multiple areas.',
		carousel: 'Carousel handoff area. This can share a camera with the feeder paths if the view covers it.',
		classification_channel:
			'Fourth C-channel path (C4). This can share a camera with the upstream feeder paths if the view covers it.',
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
			id: 'homing',
			title: 'Endstops and Homing',
			kicker: 'Step 5',
			description: 'Verify the carousel and chute endstops, then run the guided home procedures safely.',
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

	let activeStepId = $state<WizardStepId>('identity');
	let stepConfirmations = $state<WizardStepConfirmation>({});
	let progressLoadedMachineId = $state('');
	let verificationLoadedMachineId = $state('');
	let homingSectionRef = $state<SetupHomingSection | null>(null);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? backendHttpBaseUrl;
	}

	function currentBackendWsBaseUrl(): string {
		// Prefer the machine's own WS URL origin (strip path) so picker tiles
		// hit the machine we're currently connected to; fall back to the
		// globally configured WS base.
		const url = machine.machine?.url;
		if (url) {
			try {
				const parsed = new URL(url);
				return `${parsed.protocol}//${parsed.host}`;
			} catch {
				// fall through
			}
		}
		return backendWsBaseUrl;
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
		const auxiliaryRole =
			wizard?.config.machine_setup?.key === 'classification_channel'
				? 'classification_channel'
				: 'carousel';
		return [
			'c_channel_2',
			'c_channel_3',
			auxiliaryRole,
			'classification_top',
			'classification_bottom'
		];
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
		return buildCameraChoices(usbCameras, networkCameras, roleSelections, currentBackendWsBaseUrl());
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
			case 'homing':
				return Boolean(stepConfirmations.homing);
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
			case 'homing':
				return 'Endstops and homing look correct';
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
			case 'homing':
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
			if (nicknameDraft.trim().length === 0) return 'Enter a machine name to continue';
			if (savingName) return 'Saving name…';
			return null;
		},
		discovery: () => {
			if (!wizard?.readiness.boards_detected)
				return 'Waiting for controller boards to be detected';
			return null;
		},
		motion: () => {
			if (hardwareState !== 'initialized' && hardwareState !== 'ready')
				return 'Hardware must be initialized before continuing';
			return null;
		},
		homing: () => {
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
			return !savingName && nicknameDraft.trim().length > 0;
		}
		if (currentStep().requiresManualConfirm) {
			return manualConfirmEnabled(activeStepId);
		}
		return isStepComplete(activeStepId);
	}

	async function handleContinue() {
		if (activeStepId === 'identity') {
			await saveMachineName();
			return;
		}
		if (activeStepId === 'motion') {
			stepConfirmations = { ...stepConfirmations, motion: true };
		}
		if (activeStepId === 'homing') {
			if (homingSectionRef) {
				const ok = await homingSectionRef.persistPendingSettings();
				if (!ok) return;
			}
			stepConfirmations = { ...stepConfirmations, homing: true };
		}
		if (activeStepId === 'servos') {
			stepConfirmations = { ...stepConfirmations, servos: true };
		}
		goToNextStep();
	}

	async function loadWizard() {
		loadingWizard = true;
		wizardError = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/setup-wizard`);
			if (!res.ok) throw new Error(await res.text());
			const payload = (await res.json()) as WizardSummary;
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
		} catch (e: any) {
			wizardError = e.message ?? 'Failed to load setup wizard state';
		} finally {
			loadingWizard = false;
		}
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
				enabled: Boolean(entry?.enabled)
			})) satisfies HiveSetupTarget[];
		} catch (e: any) {
			hiveError = e.message ?? 'Failed to load Hive configuration.';
		} finally {
			hiveLoading = false;
		}
	}

	function connectToSorthive() {
		if (!hiveUrl.trim()) return;
		hiveConnecting = true;
		hiveError = null;
		hiveStatus = null;
		const machineName =
			(wizard?.machine.nickname ?? '').trim() ||
			nicknameDraft.trim() ||
			(wizard?.machine.machine_id ?? '');
		try {
			hiveUrl = normalizeHiveBaseUrl(hiveUrl);
			beginHiveLink({
				hiveUrl,
				targetName: 'Hive Community',
				machineName,
				returnPath: '/setup?step=hive'
			});
		} catch (e: any) {
			hiveError = e.message ?? 'Failed to start Hive linking.';
			hiveConnecting = false;
		}
	}

	async function completeSorthiveLinkIfReturned() {
		try {
			const result = await completeReturnedHiveLink(currentBackendBaseUrl());
			if (!result.completed) return;
			hiveStatus = 'Connected to Hive. Your sorter will start syncing samples in the background.';
			stepConfirmations = { ...stepConfirmations, hive: true };
			const machineId = currentMachineId();
			if (machineId && progressLoadedMachineId === machineId) {
				persistConfirmations(machineId);
			}
			await loadSorthiveConfig();
		} catch (e: any) {
			hiveError = e.message ?? 'Failed to complete Hive linking.';
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
			usbCameras = Array.isArray(payload?.usb) ? payload.usb : [];
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
			clearManualConfirmations(['motion', 'homing', 'servos', 'advanced']);
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
		void loadWizard();
		void loadCameraInventory();
	});

	$effect(() => {
		if (activeStepId !== 'motion' && activeStepId !== 'homing') return;
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

	onMount(() => {
		const machineId = currentMachineId();
		if (machineId) {
			loadStoredConfirmations(machineId);
			loadStoredVerificationState(machineId);
		}
		void completeSorthiveLinkIfReturned();
		void loadWizard();
		void loadCameraInventory();
	});
</script>

<div class="min-h-screen overflow-x-hidden bg-bg">
	<AppHeader />
	<div class="mx-auto flex max-w-[1500px] flex-col gap-6 px-4 py-6 sm:px-6">
		{#if !machine.machine}
			<section class="setup-card-shell border border-border bg-surface p-6">
				<h1 class="text-2xl font-semibold text-text">Setup Wizard</h1>
				<p class="mt-2 max-w-2xl text-sm text-text-muted">
					Select or connect a machine first. After that, this wizard will walk through the setup
					one step at a time instead of dropping the whole config surface on one page.
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
							<span class="font-mono text-text">{stepHref(activeStepId)}</span>, but it stays
							locked until the previous steps are complete.
						</div>
					{:else if activeStepId === 'identity'}
						<IdentityStep
							machineId={wizard?.machine.machine_id ??
								machine.machine.identity?.machine_id ??
								''}
							bind:nicknameDraft
							{nameError}
							{nameStatus}
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
					{:else if activeStepId === 'homing'}
						<SetupHomingSection bind:this={homingSectionRef} />
					{:else if activeStepId === 'servos'}
						<SetupServoOnboardingSection onSaved={handleServoSaved} />
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
						showFinish={isAdvanced &&
							currentStep().requiresManualConfirm &&
							!currentStepLocked()}
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
