<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount, untrack } from 'svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import LegoColorPicker from '$lib/components/LegoColorPicker.svelte';
	import SetupCameraAreaCard from '$lib/components/setup/SetupCameraAreaCard.svelte';
	import SetupHomingSection from '$lib/components/setup/SetupHomingSection.svelte';
	import SetupPictureSettingsModal from '$lib/components/setup/SetupPictureSettingsModal.svelte';
	import SetupServoOnboardingSection from '$lib/components/setup/SetupServoOnboardingSection.svelte';
	import SetupZoneEditorModal from '$lib/components/setup/SetupZoneEditorModal.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import {
		Check,
		CheckCircle2,
		ChevronLeft,
		ChevronRight,
		Cpu,
		Loader2,
		Pencil,
		RefreshCcw,
		RotateCcw
	} from 'lucide-svelte';

	type WizardSummary = {
		machine: {
			machine_id: string;
			nickname: string | null;
		};
		hardware: {
			state: string;
			error: string | null;
			homing_step: string | null;
			machine_profile: {
				camera_layout?: string;
				feeding_mode?: string;
				servo_backend?: string;
				boards?: Array<{
					family: string;
					role: string;
					device_name: string;
					port: string;
					address: number;
					logical_steppers: string[];
					input_aliases: Record<string, number>;
				}>;
			} | null;
		};
		config: {
			camera_assignments: Record<string, number | string | null>;
			feeding: {
				mode: 'auto_channels' | 'manual_carousel';
			};
			servo: {
				backend: string;
				layer_count: number;
				port: string | null;
			};
			stepper_directions: StepperDirectionEntry[];
		};
		discovery: {
			source: string;
			scanned_at_ms: number;
			mcu_ports: string[];
			boards: DiscoveredBoard[];
			roles: {
				feeder: boolean;
				distribution: boolean;
			};
			missing_required_steppers: string[];
			pca_available: boolean;
			waveshare_ports: WavesharePort[];
			usb_devices: UsbDevice[];
			issues: string[];
			recommended_camera_layout: 'default' | 'split_feeder';
		};
		readiness: Record<string, boolean>;
	};

	type DiscoveredBoard = {
		family: string;
		role: string;
		device_name: string;
		port: string;
		address: number;
		logical_steppers: string[];
		servo_count: number;
		input_aliases: Record<string, number>;
	};

	type WavesharePort = {
		device: string;
		product: string;
		serial: string | null;
	};

	type UsbDeviceCategory = 'controller' | 'servo_bus' | 'unrecognised_controller' | 'unknown';

	type UsbDevice = {
		device: string;
		product: string;
		serial: string | null;
		vid_pid: string | null;
		category: UsbDeviceCategory;
		use_by_default: boolean;
		detail: string;
		family?: string | null;
		role?: string | null;
		device_name?: string | null;
		logical_steppers?: string[];
		servo_count?: number;
	};

	type StepperDirectionEntry = {
		name: string;
		label: string;
		inverted: boolean;
		live_inverted: boolean | null;
		available: boolean;
	};

	type UsbCamera = {
		index: number;
		name: string;
	};

	type NetworkCamera = {
		id: string;
		name: string;
		source: string;
		preview_url?: string | null;
		transport: string;
	};

	type CameraChoice = {
		key: string;
		source: number | string | null;
		label: string;
		previewSrc: string | null;
	};

	type PersistedVerificationState = {
		reviewedZones?: Record<string, boolean>;
		tunedPictures?: Record<string, boolean>;
		verifiedSteppers?: Record<string, boolean>;
	};

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
		classification_top: 'Classification Top',
		classification_bottom: 'Classification Bottom'
	};
	const ROLE_DESCRIPTIONS: Record<string, string> = {
		c_channel_2: 'Feeder path for the second C-channel. You can reuse the same camera for multiple areas.',
		c_channel_3: 'Feeder path for the third C-channel. You can reuse the same camera for multiple areas.',
		carousel: 'Carousel handoff area. This can share a camera with the feeder paths if the view covers it.',
		classification_top: 'Required top-down classification view.',
		classification_bottom: 'Optional crop for underside or second-pass classification.'
	};
	const OPTIONAL_ROLES = new Set(['classification_bottom']);
	const MACHINE_NAME_INPUT_ID = 'setup-machine-name';
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
				'Review the USB controllers on this machine — we will use the ones identified as feeder, distribution and Waveshare servo bus.',
			requiresManualConfirm: false
		},
		{
			id: 'motion',
			title: 'Motion Direction Check',
			kicker: 'Step 4',
			description:
				'Jog each axis a tiny amount and confirm whether it moved clockwise or counter-clockwise. The wizard will flip any reversed logical directions automatically.',
			requiresManualConfirm: false
		},
		{
			id: 'homing',
			title: 'Endstops and Homing',
			kicker: 'Step 5',
			description:
				'Verify the carousel and chute endstops, then run the guided home procedures safely.',
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

	const SKR_PICO_WIRING_DIAGRAM_URL = '/setup/skr-pico-v1.0-headers.png';
	const DEFAULT_HIVE_URL = 'https://hive.neuhaus.nrw';

	type HiveSetupTarget = {
		id: string;
		name: string;
		url: string;
		machine_id: string | null;
		enabled: boolean;
	};

	let hiveLoading = $state(false);
	let hiveTargets = $state<HiveSetupTarget[]>([]);
	let hiveEmail = $state('');
	let hivePassword = $state('');
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

	function currentMachineId(): string {
		return machine.machine?.identity?.machine_id ?? wizard?.machine.machine_id ?? '';
	}

	function progressStorageKey(machineId: string): string {
		return `setup-wizard-progress:${machineId}`;
	}

	function verificationStorageKey(machineId: string): string {
		return `setup-wizard-verification:${machineId}`;
	}

	function loadStoredConfirmations(machineId: string) {
		if (typeof window === 'undefined' || !machineId) {
			stepConfirmations = {};
			progressLoadedMachineId = '';
			return;
		}
		try {
			const raw = window.localStorage.getItem(progressStorageKey(machineId));
			if (!raw) {
				stepConfirmations = {};
				progressLoadedMachineId = machineId;
				return;
			}
			const parsed = JSON.parse(raw);
			stepConfirmations =
				parsed && typeof parsed === 'object' ? (parsed as WizardStepConfirmation) : {};
			progressLoadedMachineId = machineId;
		} catch {
			stepConfirmations = {};
			progressLoadedMachineId = machineId;
		}
	}

	function persistConfirmations(machineId: string) {
		if (typeof window === 'undefined' || !machineId) return;
		try {
			window.localStorage.setItem(progressStorageKey(machineId), JSON.stringify(stepConfirmations));
		} catch {
			// ignore storage issues
		}
	}

	function loadStoredVerificationState(machineId: string) {
		if (typeof window === 'undefined' || !machineId) {
			reviewedZones = {};
			tunedPictures = {};
			verifiedSteppers = {};
			verificationLoadedMachineId = '';
			return;
		}
		try {
			const raw = window.localStorage.getItem(verificationStorageKey(machineId));
			if (!raw) {
				reviewedZones = {};
				tunedPictures = {};
				verifiedSteppers = {};
				verificationLoadedMachineId = machineId;
				return;
			}
			const parsed = JSON.parse(raw) as PersistedVerificationState | null;
			reviewedZones =
				parsed?.reviewedZones && typeof parsed.reviewedZones === 'object' ? parsed.reviewedZones : {};
			tunedPictures =
				parsed?.tunedPictures && typeof parsed.tunedPictures === 'object' ? parsed.tunedPictures : {};
			verifiedSteppers =
				parsed?.verifiedSteppers && typeof parsed.verifiedSteppers === 'object'
					? parsed.verifiedSteppers
					: {};
			verificationLoadedMachineId = machineId;
		} catch {
			reviewedZones = {};
			tunedPictures = {};
			verifiedSteppers = {};
			verificationLoadedMachineId = machineId;
		}
	}

	function persistVerificationState(machineId: string) {
		if (typeof window === 'undefined' || !machineId) return;
		try {
			window.localStorage.setItem(
				verificationStorageKey(machineId),
				JSON.stringify({
					reviewedZones,
					tunedPictures,
					verifiedSteppers
				} satisfies PersistedVerificationState)
			);
		} catch {
			// ignore storage issues
		}
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

	function sourceKey(source: number | string | null | undefined): string {
		if (source === null || source === undefined) return '__none__';
		if (typeof source === 'number') return `usb:${source}`;
		return `net:${source}`;
	}

	function stepperEntries(): StepperDirectionEntry[] {
		const entries = wizard?.config.stepper_directions ?? [];
		return [...entries].sort((a, b) => STEP_ORDER.indexOf(a.name) - STEP_ORDER.indexOf(b.name));
	}

	function cameraRolesForLayout(): string[] {
		return ['c_channel_2', 'c_channel_3', 'carousel', 'classification_top', 'classification_bottom'];
	}

	function roleIsRequired(role: string): boolean {
		return !OPTIONAL_ROLES.has(role);
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
		const base: CameraChoice[] = [
			{ key: '__none__', source: null, label: 'Not assigned', previewSrc: null }
		];
		for (const camera of usbCameras) {
			base.push({
				key: sourceKey(camera.index),
				source: camera.index,
				label: `${camera.name} (Camera ${camera.index})`,
				previewSrc: `${currentBackendBaseUrl()}/api/cameras/stream/${camera.index}`
			});
		}
		for (const camera of networkCameras) {
			base.push({
				key: sourceKey(camera.source),
				source: camera.source,
				label: `${camera.name} (${camera.transport})`,
				previewSrc: camera.preview_url ?? camera.source
			});
		}

		const seen = new Set(base.map((choice) => choice.key));
		for (const role of Object.keys(roleSelections)) {
			const key = roleSelections[role];
			if (!key || seen.has(key) || key === '__none__') continue;
			const source = parseCameraSource(key);
			base.push({
				key,
				source,
				label:
					typeof source === 'number' ? `Configured camera ${source}` : `Configured stream ${source}`,
				previewSrc:
					typeof source === 'number'
						? `${currentBackendBaseUrl()}/api/cameras/stream/${source}`
						: source
			});
			seen.add(key);
		}

		return base;
	}

	function parseCameraSource(key: string): number | string | null {
		if (!key || key === '__none__') return null;
		if (key.startsWith('usb:')) return Number(key.slice(4));
		if (key.startsWith('net:')) return key.slice(4);
		return null;
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

	function usbDevicesForUse(): UsbDevice[] {
		return (wizard?.discovery.usb_devices ?? []).filter((device) => device.use_by_default);
	}

	function usbCategoryBadge(category: UsbDeviceCategory): { label: string; className: string } {
		switch (category) {
			case 'controller':
				return {
					label: 'Controller',
					className: 'bg-[#00852B]/10 text-[#00852B]'
				};
			case 'servo_bus':
				return {
					label: 'Servo Bus',
					className: 'bg-[#00852B]/10 text-[#00852B]'
				};
			case 'unrecognised_controller':
				return {
					label: 'Unrecognised',
					className: 'bg-[#D01012]/10 text-[#D01012]'
				};
			default:
				return {
					label: 'Unknown',
					className: 'bg-border/60 text-text-muted'
				};
		}
	}

	function usbDeviceDisplayName(device: UsbDevice): string {
		if (device.category === 'controller') {
			const name = device.device_name || device.product || 'Control board';
			if (device.role) {
				return `${name} · ${device.role}`;
			}
			return name;
		}
		if (device.category === 'servo_bus') {
			const count = device.servo_count ?? 0;
			return `Waveshare servo bus · ${count} servo${count === 1 ? '' : 's'}`;
		}
		return device.product || 'Serial device';
	}

	function boardFamilyLabel(family: string | null | undefined): string | null {
		switch (family) {
			case 'skr_pico':
				return 'SKR Pico';
			case 'basically_rp2040':
				return 'Basically RP2040';
			case 'generic_sorter_interface':
				return 'Generic SorterInterface';
			default:
				return family ?? null;
		}
	}

	const STEPPER_LOGICAL_TO_PHYSICAL: Record<string, string> = {
		c_channel_1: 'c_channel_1_rotor',
		c_channel_2: 'c_channel_2_rotor',
		c_channel_3: 'c_channel_3_rotor',
		carousel: 'carousel',
		chute: 'chute_stepper'
	};

	// Physical port labels per board family. Indexed by canonical (logical) stepper
	// name. Add new families here as they come online.
	const STEPPER_BOARD_PORT_LABELS: Record<string, Record<string, string>> = {
		skr_pico: {
			c_channel_1: 'E0',
			c_channel_2: 'X',
			c_channel_3: 'Y',
			carousel: 'Z1',
			chute: 'E0'
		}
	};

	function boardShortLabel(family: string, role: string): string {
		const familyShort =
			family === 'skr_pico'
				? 'SKR'
				: family === 'basically_rp2040'
					? 'Basically'
					: family === 'generic_sorter_interface'
						? 'Generic'
						: family;
		const roleShort =
			role === 'feeder' ? 'Feeder' : role === 'distribution' ? 'Distributor' : role;
		return `${familyShort} ${roleShort}`;
	}

	function stepperBoardForEntry(entry: StepperDirectionEntry): DiscoveredBoard | null {
		const physical = STEPPER_LOGICAL_TO_PHYSICAL[entry.name];
		if (!physical) return null;
		const boards = wizard?.discovery.boards ?? [];
		return boards.find((board) => board.logical_steppers.includes(physical)) ?? null;
	}

	function stepperLocationLabel(entry: StepperDirectionEntry): string {
		const board = stepperBoardForEntry(entry);
		if (!board) {
			return entry.available ? 'Live stepper available' : 'Not connected';
		}
		const boardLabel = boardShortLabel(board.family, board.role);
		const port = STEPPER_BOARD_PORT_LABELS[board.family]?.[entry.name];
		return port ? `${boardLabel} · ${port}` : boardLabel;
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
				// Theme step is informational — picking a color is optional, the
				// default is LEGO Blue. Mark it complete unconditionally so it
				// never blocks the wizard.
				return true;
			case 'discovery':
				return Boolean(wizard?.readiness.boards_detected);
			case 'cameras':
				return Boolean(wizard?.readiness.camera_layout_selected) && Boolean(wizard?.readiness.cameras_assigned);
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

	function setActiveStep(stepId: WizardStepId) {
		if (!canOpenStep(stepId)) return;
		void navigateToStep(stepId);
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

	async function connectToSorthive() {
		if (!hiveEmail.trim() || !hivePassword.trim()) return;
		hiveConnecting = true;
		hiveError = null;
		hiveStatus = null;
		const machineName =
			(wizard?.machine.nickname ?? '').trim() ||
			nicknameDraft.trim() ||
			(wizard?.machine.machine_id ?? '');
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive/register`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					target_name: 'Hive Community',
					url: DEFAULT_HIVE_URL,
					email: hiveEmail.trim(),
					password: hivePassword.trim(),
					machine_name: machineName,
					machine_description: ''
				})
			});
			if (!res.ok) {
				let message = await res.text();
				try {
					const body = JSON.parse(message);
					message = body.detail ?? body.error ?? message;
				} catch {
					// use raw text
				}
				throw new Error(message || 'Failed to connect to Hive.');
			}
			hivePassword = '';
			hiveStatus = 'Connected to Hive. Your sorter will start syncing samples in the background.';
			stepConfirmations = { ...stepConfirmations, hive: true };
			const machineId = currentMachineId();
			if (machineId && progressLoadedMachineId === machineId) {
				persistConfirmations(machineId);
			}
			await loadSorthiveConfig();
		} catch (e: any) {
			hiveError = e.message ?? 'Failed to connect to Hive.';
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
			usbCameras = Array.isArray(payload?.usb) ? payload.usb : [];
			networkCameras = Array.isArray(payload?.network) ? payload.network : [];
		} catch (e: any) {
			cameraError = e.message ?? 'Failed to load camera inventory';
		} finally {
			loadingCameras = false;
		}
	}

	async function pollSystemStatus() {
		try {
			const previousState = hardwareState;
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/status`);
			if (!res.ok) return;
			const payload = await res.json();
			hardwareState = payload.hardware_state ?? 'standby';
			hardwareError = payload.hardware_error ?? null;
			homingStep = payload.homing_step ?? null;
			if (hardwareState !== previousState) {
				void loadWizard();
			}
		} catch {
			// ignore polling errors
		}
	}

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

	async function saveLayout() {
		savingLayout = true;
		layoutStatus = '';
		layoutError = null;
		try {
			const layoutChanged = wizard?.config.camera_assignments.layout !== selectedLayout;
			const res = await fetch(`${currentBackendBaseUrl()}/api/setup-wizard/camera-layout`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ layout: selectedLayout })
			});
			if (!res.ok) throw new Error(await res.text());
			clearManualConfirmations(['motion', 'homing', 'servos', 'advanced']);
			if (layoutChanged) {
				clearAllCameraVerification();
			}
			layoutStatus =
				selectedLayout === 'split_feeder'
					? 'Split feeder layout selected.'
					: 'Single feeder layout selected.';
			await loadWizard();
		} catch (e: any) {
			layoutError = e.message ?? 'Failed to save camera layout';
		} finally {
			savingLayout = false;
		}
	}
	async function saveCameraAssignments() {
		savingAssignments = true;
		cameraError = null;
		cameraStatus = '';
		try {
			const changedRoles = cameraRolesForLayout().filter(
				(role) => sourceKey(wizard?.config.camera_assignments[role] ?? null) !== (roleSelections[role] ?? '__none__')
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
			await pollSystemStatus();
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

	async function recordObservedDirection(
		entry: StepperDirectionEntry,
		observed: 'cw' | 'ccw'
	) {
		// Convention: the Jog button always commands a "logical clockwise" pulse.
		// If the operator observed clockwise, the current inverted flag is correct;
		// otherwise we need to flip it.
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
		// Auto-initialize the steppers as soon as the operator opens the Motion
		// Direction Check or Endstops & Homing step. No homing — just enough so
		// the jog/live-status APIs have an active hardware connection.
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
		void loadWizard();
		void loadCameraInventory();
		void pollSystemStatus();
		const interval = setInterval(() => {
			void pollSystemStatus();
		}, 1500);
		return () => clearInterval(interval);
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
				<div class="border border-[#D01012] bg-[#D01012]/10 px-4 py-3 text-sm text-[#D01012]">
					{wizardError}
				</div>
			{/if}

			<div class="flex flex-col gap-6">
					<section class="setup-card-shell overflow-hidden border border-border">
						<div class="setup-card-body px-6 py-6">
							<ol class="flex w-full items-start">
								{#each WIZARD_STEPS as step, index}
									{@const status = stepStatus(step.id)}
									{@const isFirst = index === 0}
									{@const isLast = index === WIZARD_STEPS.length - 1}
									{@const prevStatus = index > 0 ? stepStatus(WIZARD_STEPS[index - 1].id) : null}
									<li class="relative flex min-w-0 flex-1 flex-col items-center">
										{#if !isFirst}
											<div
												class={`absolute left-0 top-5 -ml-px h-0.5 w-1/2 ${
													prevStatus === 'done' ? 'bg-[#00852B]' : 'bg-border'
												}`}
											></div>
										{/if}
										{#if !isLast}
											<div
												class={`absolute right-0 top-5 -mr-px h-0.5 w-1/2 ${
													status === 'done' ? 'bg-[#00852B]' : 'bg-border'
												}`}
											></div>
										{/if}
										<button
											type="button"
											onclick={() => setActiveStep(step.id)}
											disabled={!canOpenStep(step.id)}
											aria-label={step.title}
											class={`relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${
												status === 'done'
													? 'border-[#00852B] bg-[#00852B] text-white hover:bg-[#006e24]'
													: status === 'current'
														? 'border-[#00852B] bg-white text-[#00852B]'
														: 'border-border bg-white text-text-muted'
											}`}
										>
											{#if status === 'done'}
												<Check size={18} strokeWidth={3} />
											{:else if status === 'current'}
												<Pencil size={15} strokeWidth={2.5} />
											{:else}
												{index + 1}
											{/if}
										</button>
										<div
											class={`mt-2 px-1 text-center text-xs font-medium leading-4 ${
												status === 'done' || status === 'current'
													? 'text-[#00852B]'
													: 'text-text-muted'
											}`}
										>
											{step.title}
										</div>
									</li>
								{/each}
							</ol>
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
							<div
								class="border border-[#D01012] bg-[#D01012]/10 px-4 py-3 text-sm text-[#D01012]"
							>
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
								<span class="font-mono text-text">{stepHref(activeStepId)}</span>,
								but it stays locked until the previous steps are complete.
							</div>
						{:else if activeStepId === 'identity'}
							<div class="flex flex-col gap-4">
								<div class="text-xs text-text-muted">
									Machine ID:
									<span class="font-mono text-text"
										>{wizard?.machine.machine_id ??
											machine.machine.identity?.machine_id ??
											'—'}</span
									>
								</div>
								<div>
									<label
										for={MACHINE_NAME_INPUT_ID}
										class="mb-2 block text-sm font-medium text-text"
									>
										Machine name
									</label>
									<input
										id={MACHINE_NAME_INPUT_ID}
										type="text"
										bind:value={nicknameDraft}
										placeholder="e.g. Sorting Bench A"
										class="setup-control w-full px-3 py-2 text-sm text-text"
									/>
								</div>
								{#if nameError}
									<div class="text-sm text-[#D01012]">{nameError}</div>
								{:else if nameStatus}
									<div class="text-sm text-[#00852B]">{nameStatus}</div>
								{/if}
							</div>
						{:else if activeStepId === 'theme'}
							<div class="flex flex-col gap-4">
								<div class="text-sm text-text-muted">
									Pick the LEGO color you want to see across the UI. Buttons,
									focus rings, and active highlights will switch immediately
									— no reload needed.
								</div>
								<LegoColorPicker />
							</div>
						{:else if activeStepId === 'discovery'}
							<div class="flex flex-col gap-4">
								<div class="flex flex-wrap items-center gap-3 text-sm">
									<div class="setup-panel inline-flex items-center gap-2 px-3 py-2 text-text">
										<Cpu size={14} />
										<span
											>{usbDevicesForUse().length} controller{usbDevicesForUse().length === 1 ? '' : 's'} in use</span
										>
									</div>
									<button
										onclick={loadWizard}
										disabled={loadingWizard}
										class="setup-button-secondary inline-flex items-center gap-2 px-3 py-2 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
									>
										<RefreshCcw size={14} class={loadingWizard ? 'animate-spin' : ''} />
										Rescan
									</button>
								</div>

								{#if wizard?.discovery.issues.length}
									<div
										class="border border-[#D01012] bg-[#D01012]/10 px-4 py-3 text-sm text-[#D01012]"
									>
										{#each wizard.discovery.issues as issue}
											<div>{issue}</div>
										{/each}
									</div>
								{/if}

								{#if !(wizard?.discovery.usb_devices?.length)}
									<div class="setup-panel px-4 py-3 text-sm text-text-muted">
										No USB controllers are visible right now. Check power and USB
										connections, then rescan.
									</div>
								{:else}
									<div class="flex flex-col gap-2">
										{#each wizard.discovery.usb_devices as device}
											{@const badge = usbCategoryBadge(device.category)}
											{@const familyLabel = boardFamilyLabel(device.family)}
											<label
												class={`setup-panel flex items-start gap-3 px-4 py-3 transition-colors ${
													device.use_by_default ? 'border-[#00852B]/40 bg-[#EAF7EE]' : ''
												}`}
											>
												<input
													type="checkbox"
													checked={device.use_by_default}
													disabled
													class="mt-1 h-4 w-4 accent-[#00852B]"
												/>
												<div class="min-w-0 flex-1">
													<div class="flex flex-wrap items-center gap-2">
														<span class="text-sm font-medium text-text">
															{usbDeviceDisplayName(device)}
														</span>
														<span class={`px-2 py-0.5 text-[11px] font-semibold tracking-wide uppercase ${badge.className}`}>
															{badge.label}
														</span>
														{#if familyLabel}
															<span class="bg-border/40 px-2 py-0.5 text-[11px] font-semibold tracking-wide text-text-muted uppercase">
																{familyLabel}
															</span>
														{/if}
													</div>
													<div class="mt-1 font-mono text-xs text-text-muted">{device.device}{device.vid_pid ? ` · ${device.vid_pid}` : ''}</div>
													{#if device.detail}
														<div class="mt-1 text-xs text-text-muted">{device.detail}</div>
													{/if}
												</div>
											</label>
										{/each}
									</div>
								{/if}
							</div>
						{:else if activeStepId === 'cameras'}
							<div class="flex flex-col gap-4">
								<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
									{#each cameraRolesForLayout() as role}
										<SetupCameraAreaCard
											role={role as any}
											label={ROLE_LABELS[role]}
											description={ROLE_DESCRIPTIONS[role]}
											required={roleIsRequired(role)}
											selectedKey={roleSelections[role] ?? '__none__'}
											selectedLabel={selectedCameraLabel(roleSelections[role])}
											zoneReviewed={Boolean(reviewedZones[role])}
											pictureTuned={Boolean(tunedPictures[role])}
											choices={cameraChoices().filter((choice) => choice.key !== '__none__') as any}
											onSelect={handleRoleSelection}
											onOpenPictureSettings={openPictureSettings}
											onOpenZoneEditor={openZoneEditor}
										/>
									{/each}
								</div>

								<div class="flex flex-wrap items-center gap-3">
									<button
										onclick={saveCameraAssignments}
										disabled={savingAssignments || savingLayout}
										class="setup-button-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
									>
										<CheckCircle2 size={14} />
										{savingAssignments ? 'Saving...' : 'Save Camera Setup'}
									</button>
								</div>

								{#if cameraError}
									<div class="text-sm text-[#D01012]">{cameraError}</div>
								{:else if cameraStatus}
									<div class="text-sm text-[#00852B]">{cameraStatus}</div>
								{/if}

							</div>
						{:else if activeStepId === 'motion'}
							{@const steppersLive =
								hardwareState === 'initialized' || hardwareState === 'ready'}
							{@const steppersInitializing =
								homingSystem || hardwareState === 'initializing' || hardwareState === 'homing'}
							<div class="flex flex-col gap-4">
								{#if hardwareError}
									<div
										class="flex flex-wrap items-center justify-between gap-3 border border-[#D01012] bg-[#D01012]/10 px-4 py-3 text-sm text-[#D01012]"
									>
										<span>{hardwareError}</span>
										<button
											onclick={initializeSteppers}
											disabled={steppersInitializing}
											class="setup-button-secondary inline-flex items-center gap-2 px-3 py-1.5 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
										>
											<RotateCcw size={14} />
											Retry
										</button>
									</div>
								{/if}

								{#if steppersInitializing}
									<div
										class="flex items-center gap-3 border border-[#F2A900] bg-[#FFF7E0] px-4 py-3 text-sm text-[#7A5A00]"
									>
										<Loader2 size={18} class="animate-spin" />
										<div class="flex flex-col">
											<span class="font-medium">Powering on steppers…</span>
											<span class="text-xs text-[#7A5A00]/80">
												{homingStep ?? 'Discovering hardware'} — jog controls unlock once the
												boards are ready.
											</span>
										</div>
									</div>
								{/if}

								<div class="setup-panel px-4 py-3 text-sm text-text-muted">
									<div class="flex flex-wrap items-start justify-between gap-3">
										<div class="min-w-0 flex-1">
											Use very short jogs on an empty machine to verify that each axis turns in the
											expected direction. Reverse any axis that runs the wrong way, then mark this
											step as done — the next step covers endstops and the real homing routine.
										</div>
										<button
											onclick={() => (showStepperWiringHelp = !showStepperWiringHelp)}
											class="setup-button-secondary inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-text transition-colors"
										>
											{showStepperWiringHelp ? 'Hide wiring help' : 'Show wiring help'}
										</button>
									</div>
								</div>

								{#if showStepperWiringHelp}
									<div class="setup-panel px-4 py-4 text-sm text-text">
										<div class="text-sm font-semibold text-text">SKR Pico stepper wiring</div>
										<div class="mt-1 text-xs text-text-muted">
											Reference for the SKR Pico V1.0 stepper headers used by the feeder and
											distributor boards.
										</div>
										<div class="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
											<a
												href={SKR_PICO_WIRING_DIAGRAM_URL}
												target="_blank"
												rel="noopener noreferrer"
												class="block border border-border bg-white p-1"
											>
												<img
													src={SKR_PICO_WIRING_DIAGRAM_URL}
													alt="SKR Pico V1.0 wiring diagram"
													loading="lazy"
													class="block h-auto w-full"
												/>
											</a>
											<div class="flex flex-col gap-3 text-xs">
												<div>
													<div class="font-semibold tracking-wide text-text uppercase">
														Sorter mapping
													</div>
													<table class="mt-2 w-full border-collapse">
														<tbody>
															<tr class="border-b border-border">
																<td class="py-1 text-text">C-Channel 1</td>
																<td class="py-1 font-mono text-text-muted">SKR Feeder · E0</td>
															</tr>
															<tr class="border-b border-border">
																<td class="py-1 text-text">C-Channel 2</td>
																<td class="py-1 font-mono text-text-muted">SKR Feeder · X</td>
															</tr>
															<tr class="border-b border-border">
																<td class="py-1 text-text">C-Channel 3</td>
																<td class="py-1 font-mono text-text-muted">SKR Feeder · Y</td>
															</tr>
															<tr class="border-b border-border">
																<td class="py-1 text-text">Carousel</td>
																<td class="py-1 font-mono text-text-muted">SKR Feeder · Z1</td>
															</tr>
															<tr>
																<td class="py-1 text-text">Chute</td>
																<td class="py-1 font-mono text-text-muted">
																	SKR Distributor · E0
																</td>
															</tr>
														</tbody>
													</table>
												</div>
											</div>
										</div>
									</div>
								{/if}

								<div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
									{#each stepperEntries() as entry}
										{@const isVerified = !!verifiedSteppers[entry.name]}
										<div
											class={`setup-panel relative p-4 transition-colors ${
												isVerified ? '!border-[#00852B] !bg-[#D4EDDA]' : ''
											}`}
										>
											{#if isVerified}
												<div
													class="absolute top-2 right-2 inline-flex items-center gap-1 bg-[#00852B] px-2 py-0.5 text-[10px] font-semibold tracking-wide text-white uppercase"
												>
													<Check size={12} />
													Verified
												</div>
											{/if}
											<div class="flex items-center justify-between gap-3 pr-20">
												<div class="min-w-0">
													<div class="text-sm font-medium text-text">{entry.label}</div>
													<div class="text-xs text-text-muted">
														{stepperLocationLabel(entry)}
													</div>
												</div>
												<div
													class={`text-xs ${entry.inverted ? 'text-[#D01012]' : 'text-[#00852B]'}`}
												>
													{entry.inverted ? 'Inverted' : 'Normal'}
												</div>
											</div>

											<div class="mt-4 flex justify-center">
												<button
													onclick={() => pulseStepper(entry.name, 'cw')}
													disabled={!steppersLive || !!stepperBusy[`${entry.name}:cw`]}
													class="inline-flex items-center justify-center border border-primary bg-primary px-6 py-1.5 text-xs font-medium text-primary-contrast transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
												>
													Jog
												</button>
											</div>
											<div class="mt-3 text-center text-xs text-text-muted">
												Which way did it move?
											</div>
											<div class="mt-1 grid grid-cols-2 gap-2">
												<button
													onclick={() => recordObservedDirection(entry, 'cw')}
													disabled={!steppersLive || togglingStepper === entry.name}
													class="setup-button-secondary px-3 py-2 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-50"
												>
													Clockwise
												</button>
												<button
													onclick={() => recordObservedDirection(entry, 'ccw')}
													disabled={!steppersLive || togglingStepper === entry.name}
													class="setup-button-secondary px-3 py-2 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-50"
												>
													Counter-Clockwise
												</button>
											</div>
										</div>
									{/each}
								</div>

								{#if stepperActionError}
									<div class="text-sm text-[#D01012]">{stepperActionError}</div>
								{/if}
							</div>
						{:else if activeStepId === 'homing'}
							<SetupHomingSection bind:this={homingSectionRef} />
						{:else if activeStepId === 'servos'}
							<SetupServoOnboardingSection onSaved={handleServoSaved} />
						{:else if activeStepId === 'hive'}
							<div class="flex flex-col gap-4">
								{#if hiveLoading}
									<div class="setup-panel flex items-center gap-2 px-4 py-3 text-sm text-text-muted">
										<Loader2 size={14} class="animate-spin" />
										Checking current Hive configuration…
									</div>
								{:else if officialSorthiveTarget}
									<div
										class="border border-[#00852B]/40 bg-[#00852B]/[0.06] px-4 py-3 dark:border-emerald-500/40 dark:bg-emerald-500/[0.08]"
									>
										<div class="flex items-start gap-3">
											<div
												class="mt-0.5 flex h-6 w-6 items-center justify-center rounded-full bg-[#00852B] text-white"
											>
												<Check size={14} strokeWidth={3} />
											</div>
											<div class="flex min-w-0 flex-1 flex-col gap-1">
												<div class="text-[11px] font-semibold tracking-wider text-[#003D14] uppercase dark:text-emerald-200">
													Connected to Hive
												</div>
												<div class="text-xs leading-relaxed text-text">
													This sorter is registered with
													<span class="font-mono">{officialSorthiveTarget.url}</span>.
												</div>
												{#if officialSorthiveTarget.machine_id}
													<div class="text-[11px] text-text-muted">
														Machine ID
														<span class="font-mono text-text">{officialSorthiveTarget.machine_id}</span>
													</div>
												{/if}
											</div>
										</div>
									</div>
									<div class="text-xs text-text-muted">
										You can manage this connection later under Settings › Hive. Click
										Continue to finish the setup wizard.
									</div>
								{:else}
									<div class="setup-panel flex flex-col gap-2 px-4 py-3">
										<div class="text-[11px] font-semibold tracking-wider text-text-muted uppercase">
											Hive server
										</div>
										<div class="font-mono text-sm text-text">{DEFAULT_HIVE_URL}</div>
										<div class="text-xs text-text-muted">
											The official community platform. Additional servers can be added later
											from Settings › Hive.
										</div>
									</div>

									<div class="grid gap-3 sm:grid-cols-2">
										<div class="flex flex-col gap-1">
											<label
												for="setup-hive-email"
												class="text-xs font-medium text-text"
											>
												Email
											</label>
											<input
												id="setup-hive-email"
												type="email"
												autocomplete="email"
												bind:value={hiveEmail}
												placeholder="you@example.com"
												class="setup-control px-3 py-2 text-sm text-text"
												disabled={hiveConnecting}
											/>
										</div>
										<div class="flex flex-col gap-1">
											<label
												for="setup-hive-password"
												class="text-xs font-medium text-text"
											>
												Password
											</label>
											<input
												id="setup-hive-password"
												type="password"
												autocomplete="current-password"
												bind:value={hivePassword}
												placeholder="••••••••"
												class="setup-control px-3 py-2 text-sm text-text"
												disabled={hiveConnecting}
											/>
										</div>
									</div>

									<div class="setup-panel flex flex-col gap-1 px-4 py-3">
										<div class="text-[11px] font-semibold tracking-wider text-text-muted uppercase">
											Machine name
										</div>
										<div class="text-sm text-text">
											{(wizard?.machine.nickname ?? '').trim() ||
												nicknameDraft.trim() ||
												wizard?.machine.machine_id ||
												'Unnamed sorter'}
										</div>
										<div class="text-[11px] text-text-muted">
											This is how your sorter will appear in Hive. Change it in Step 1
											if needed.
										</div>
									</div>

									<div class="flex flex-wrap items-center gap-2">
										<button
											type="button"
											onclick={connectToSorthive}
											disabled={hiveConnecting ||
												!hiveEmail.trim() ||
												!hivePassword.trim()}
											class="inline-flex items-center gap-2 border border-[#00852B] bg-[#00852B] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[#00852B]/90 disabled:cursor-not-allowed disabled:opacity-60"
										>
											{#if hiveConnecting}
												<Loader2 size={14} class="animate-spin" />
												Connecting…
											{:else}
												<CheckCircle2 size={14} />
												Connect to Hive
											{/if}
										</button>
										<button
											type="button"
											onclick={skipSorthive}
											disabled={hiveConnecting}
											class="setup-button-secondary inline-flex items-center gap-2 px-3 py-2 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
										>
											Skip for now
										</button>
									</div>
								{/if}

								{#if hiveError}
									<div
										class="border border-[#D01012]/40 bg-[#D01012]/[0.06] px-3 py-2 text-xs leading-relaxed text-text dark:border-rose-500/40 dark:bg-rose-500/[0.08]"
									>
										<div class="mb-1 text-[11px] font-semibold tracking-wider text-[#5C0708] uppercase dark:text-rose-200">
											Hive connection failed
										</div>
										{hiveError}
									</div>
								{:else if hiveStatus}
									<div
										class="border border-[#00852B]/40 bg-[#00852B]/[0.06] px-3 py-2 text-xs leading-relaxed text-text dark:border-emerald-500/40 dark:bg-emerald-500/[0.08]"
									>
										{hiveStatus}
									</div>
								{/if}
							</div>
						{:else if activeStepId === 'advanced'}
							<div
								class="setup-panel relative overflow-hidden border-[#00852B]/40 bg-gradient-to-br from-[#EAF7EE] via-[#F3FBF5] to-white px-8 py-10 text-center dark:from-[#0F2B18] dark:via-[#0B1F12] dark:to-bg"
							>
								<div class="mx-auto flex max-w-xl flex-col items-center gap-4">
									<div
										class="flex h-20 w-20 items-center justify-center rounded-full bg-[#00852B] text-white shadow-[0_8px_24px_-6px_rgba(0,133,43,0.55)]"
									>
										<Check size={44} strokeWidth={3} />
									</div>
									<div class="flex flex-col gap-2">
										<div class="text-2xl font-bold text-text">Setup Complete!</div>
										<div class="text-sm text-text-muted">
											Your sorter is configured and ready to go. Open the dashboard, home the
											machine if it's still in standby, and give it a first run.
										</div>
									</div>
								</div>
							</div>
						{/if}

						<div
							class="mt-6 flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-end"
						>
							<div class="flex flex-wrap items-center gap-2">
								{#if currentStepNumber() > 1}
									<button
										onclick={goToPreviousStep}
										class="setup-button-secondary inline-flex items-center gap-2 px-3 py-2 text-sm text-text transition-colors"
									>
										<ChevronLeft size={14} />
										Back
									</button>
								{/if}

								{#if activeStepId === 'advanced' && currentStep().requiresManualConfirm && !currentStepLocked()}
									<button
										onclick={finishSetup}
										disabled={!manualConfirmEnabled(activeStepId) || isStepComplete(activeStepId)}
										class="inline-flex items-center gap-2 border border-[#00852B] bg-[#00852B] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[#00852B]/90 disabled:cursor-not-allowed disabled:opacity-60"
									>
										<CheckCircle2 size={14} />
										{manualConfirmLabel(activeStepId)}
									</button>
								{/if}

								{#if activeStepId !== 'advanced'}
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
									<button
										onclick={handleContinue}
										disabled={continueDisabled}
										class="setup-button-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
									>
										{continueLabel}
										<ChevronRight size={14} />
									</button>
								{/if}
							</div>
						</div>
					</SectionCard>

				</div>
		{/if}

		<Modal open={pictureSettingsRole !== null} title="Picture Settings" wide={true} on:close={closePictureSettings}>
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
