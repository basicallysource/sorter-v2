<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import SetupHomingSection from '$lib/components/setup/SetupHomingSection.svelte';
	import SetupServoOnboardingSection from '$lib/components/setup/SetupServoOnboardingSection.svelte';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import StorageLayerSettingsSection from '$lib/components/settings/StorageLayerSettingsSection.svelte';
	import {
		Camera,
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
		transport: string;
	};

	type CameraChoice = {
		key: string;
		source: number | string | null;
		label: string;
	};

	type WizardStepId =
		| 'identity'
		| 'discovery'
		| 'layout'
		| 'cameras'
		| 'motion'
		| 'homing'
		| 'servos'
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
		feeder: 'Feeder Camera',
		c_channel_2: 'C-Channel 2 Camera',
		c_channel_3: 'C-Channel 3 Camera',
		carousel: 'Carousel Camera',
		classification_top: 'Classification Top',
		classification_bottom: 'Classification Bottom'
	};
	const OPTIONAL_ROLES = new Set(['classification_top', 'classification_bottom']);
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
			id: 'discovery',
			title: 'Controller Discovery',
			kicker: 'Step 2',
			description:
				'Review the USB controllers on this machine — we will use the ones identified as feeder, distribution and Waveshare servo bus.',
			requiresManualConfirm: false
		},
		{
			id: 'motion',
			title: 'Motion Direction Check',
			kicker: 'Step 3',
			description:
				'Jog each axis a tiny amount and confirm whether it moved clockwise or counter-clockwise. The wizard will flip any reversed logical directions automatically.',
			requiresManualConfirm: false
		},
		{
			id: 'homing',
			title: 'Endstops and Homing',
			kicker: 'Step 4',
			description:
				'Verify the carousel and chute endstops, then run the guided home procedures safely.',
			requiresManualConfirm: true
		},
		{
			id: 'servos',
			title: 'Servo Configuration',
			kicker: 'Step 5',
			description:
				'Discover the servos on the bus, calibrate and assign each one to a storage layer one-by-one.',
			requiresManualConfirm: true
		},
		{
			id: 'layout',
			title: 'Camera Setup',
			kicker: 'Step 6',
			description:
				'Decide whether this machine runs the simple single-feeder layout or the split-feeder multi-camera layout.',
			requiresManualConfirm: false
		},
		{
			id: 'cameras',
			title: 'Camera Assignment',
			kicker: 'Step 7',
			description: 'Assign a physical stream to each role required by the chosen camera layout.',
			requiresManualConfirm: false
		},
		{
			id: 'advanced',
			title: 'Finish and Fine Tuning',
			kicker: 'Step 8',
			description:
				'Use the detailed editors for deeper storage-layer tuning and optional camera geometry calibration.',
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

	let hardwareState = $state('standby');
	let hardwareError = $state<string | null>(null);
	let homingStep = $state<string | null>(null);
	let homingSystem = $state(false);
	let resettingSystem = $state(false);
	let systemStatusMsg = $state('');

	let stepperActionError = $state<string | null>(null);
	let stepperActionStatus = $state('');
	let stepperBusy = $state<Record<string, boolean>>({});
	let togglingStepper = $state<string | null>(null);
	let verifiedSteppers = $state<Record<string, boolean>>({});
	let showStepperWiringHelp = $state(false);

	const SKR_PICO_WIRING_DIAGRAM_URL = '/setup/skr-pico-v1.0-headers.png';

	let activeStepId = $state<WizardStepId>('identity');
	let stepConfirmations = $state<WizardStepConfirmation>({});
	let progressLoadedMachineId = $state('');
	let homingSectionRef = $state<SetupHomingSection | null>(null);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? backendHttpBaseUrl;
	}

	function progressStorageKey(machineId: string): string {
		return `setup-wizard-progress:${machineId}`;
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
		return selectedLayout === 'split_feeder'
			? ['c_channel_2', 'c_channel_3', 'carousel', 'classification_top', 'classification_bottom']
			: ['feeder', 'classification_top', 'classification_bottom'];
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
		const base: CameraChoice[] = [{ key: '__none__', source: null, label: 'Not assigned' }];
		for (const camera of usbCameras) {
			base.push({
				key: sourceKey(camera.index),
				source: camera.index,
				label: `${camera.name} (Camera ${camera.index})`
			});
		}
		for (const camera of networkCameras) {
			base.push({
				key: sourceKey(camera.source),
				source: camera.source,
				label: `${camera.name} (${camera.transport})`
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
					typeof source === 'number' ? `Configured camera ${source}` : `Configured stream ${source}`
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
			case 'discovery':
				return Boolean(wizard?.readiness.boards_detected);
			case 'layout':
				return Boolean(wizard?.readiness.camera_layout_selected);
			case 'cameras':
				return Boolean(wizard?.readiness.cameras_assigned);
			case 'motion':
				return Boolean(stepConfirmations.motion);
			case 'homing':
				return Boolean(stepConfirmations.homing);
			case 'servos':
				return Boolean(wizard?.readiness.servo_configured) && Boolean(stepConfirmations.servos);
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
			case 'advanced':
				return 'Finish wizard';
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
			case 'advanced':
				return true;
			default:
				return true;
		}
	}

	function markCurrentStepComplete() {
		stepConfirmations = {
			...stepConfirmations,
			[activeStepId]: true
		};
		if (activeStepId !== 'advanced') {
			goToNextStep();
		}
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
			const res = await fetch(`${currentBackendBaseUrl()}/api/setup-wizard/camera-layout`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ layout: selectedLayout })
			});
			if (!res.ok) throw new Error(await res.text());
			clearManualConfirmations(['motion', 'homing', 'servos', 'advanced']);
				layoutStatus =
					selectedLayout === 'split_feeder'
						? 'Split feeder layout selected.'
						: 'Single feeder layout selected.';
				await loadWizard();
				await navigateToStep('cameras');
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
			const payload: Record<string, number | string | null> = { layout: selectedLayout };
			for (const role of cameraRolesForLayout()) {
				payload[role] = parseCameraSource(roleSelections[role] ?? '__none__');
			}
			if (selectedLayout === 'split_feeder') {
				payload.feeder = null;
			} else {
				payload.c_channel_2 = null;
				payload.c_channel_3 = null;
				payload.carousel = null;
			}

			const res = await fetch(`${currentBackendBaseUrl()}/api/cameras/assign`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload)
			});
			if (!res.ok) throw new Error(await res.text());
				clearManualConfirmations(['motion', 'homing', 'servos', 'advanced']);
				cameraStatus = 'Camera assignments saved.';
				await loadWizard();
				await navigateToStep('motion');
			} catch (e: any) {
				cameraError = e.message ?? 'Failed to save camera assignments';
			} finally {
			savingAssignments = false;
		}
	}

	async function homeSystem() {
		homingSystem = true;
		systemStatusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/home`, { method: 'POST' });
			if (!res.ok) throw new Error(await res.text());
			systemStatusMsg = 'Hardware initialization started.';
			await pollSystemStatus();
		} catch (e: any) {
			hardwareError = e.message ?? 'Failed to start homing';
		} finally {
			homingSystem = false;
		}
	}

	async function initializeSteppers() {
		homingSystem = true;
		systemStatusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/initialize`, {
				method: 'POST'
			});
			if (!res.ok) throw new Error(await res.text());
			systemStatusMsg = 'Powering on steppers...';
			await pollSystemStatus();
		} catch (e: any) {
			hardwareError = e.message ?? 'Failed to power on steppers';
		} finally {
			homingSystem = false;
		}
	}

	async function resetSystem() {
		resettingSystem = true;
		systemStatusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/reset`, { method: 'POST' });
			if (!res.ok) throw new Error(await res.text());
			clearManualConfirmations(['motion', 'homing', 'advanced']);
			systemStatusMsg = 'Hardware reset back to standby.';
			await pollSystemStatus();
		} catch (e: any) {
			hardwareError = e.message ?? 'Failed to reset hardware';
		} finally {
			resettingSystem = false;
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
		const machineId = machine.machine?.identity?.machine_id ?? wizard?.machine.machine_id ?? '';
		if (!machineId || progressLoadedMachineId !== machineId) return;
		persistConfirmations(machineId);
	});

	$effect(() => {
		const routeStep = parseRouteStep(page.url.searchParams.get('step'));
		activeStepId = routeStep ?? 'identity';
		if (routeStep === null) {
			void navigateToStep('identity', true);
		}
	});

	$effect(() => {
		const machineId = machine.machine?.identity?.machine_id ?? '';
		if (!machineId || machineId === loadedMachineKey) return;
		loadedMachineKey = machineId;
		loadStoredConfirmations(machineId);
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

	onMount(() => {
		const machineId = machine.machine?.identity?.machine_id ?? '';
		if (machineId) {
			loadStoredConfirmations(machineId);
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
						<div class="setup-card-body p-6">
							<div class="flex items-start">
								{#each WIZARD_STEPS as step, index}
									{@const status = stepStatus(step.id)}
									{@const isLast = index === WIZARD_STEPS.length - 1}
									<div class="flex min-w-0 flex-1 items-start">
										<div class="flex min-w-0 flex-col items-center gap-2">
											<button
												type="button"
												onclick={() => setActiveStep(step.id)}
												disabled={!canOpenStep(step.id)}
												aria-label={step.title}
												class={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${
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
												class={`truncate px-1 text-center text-xs font-medium ${
													status === 'done' || status === 'current'
														? 'text-[#00852B]'
														: 'text-text-muted'
												}`}
											>
												{step.title}
											</div>
										</div>
										{#if !isLast}
											<div
												class={`mt-5 h-0.5 flex-1 ${
													status === 'done' ? 'bg-[#00852B]' : 'bg-border'
												}`}
											></div>
										{/if}
									</div>
								{/each}
							</div>
						</div>
					</section>

					<SectionCard
						title={currentStep().title}
						description={currentStep().description}
						rootClass="setup-card-shell"
						headerClass="setup-card-header"
						bodyClass="setup-card-body"
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
						{:else if activeStepId === 'layout'}
							<div class="flex flex-col gap-4">
								<div class="grid gap-3 md:grid-cols-2">
									<button
										onclick={() => (selectedLayout = 'default')}
										class={`setup-choice px-4 py-4 text-left transition-colors ${
											selectedLayout === 'default' ? 'border-[#0055BF] bg-[#0055BF]/10' : ''
										}`}
									>
										<div class="flex items-center justify-between gap-3">
											<div class="text-sm font-semibold text-text">Single feeder</div>
											{#if wizard?.discovery.recommended_camera_layout === 'default'}
												<span
													class="rounded-full bg-[#0055BF]/10 px-2 py-1 text-[11px] font-medium text-[#0055BF]"
												>
													Recommended
												</span>
											{/if}
										</div>
										<div class="mt-2 text-sm text-text-muted">
											One feeder camera plus optional classification cameras.
										</div>
									</button>
									<button
										onclick={() => (selectedLayout = 'split_feeder')}
										class={`setup-choice px-4 py-4 text-left transition-colors ${
											selectedLayout === 'split_feeder' ? 'border-[#0055BF] bg-[#0055BF]/10' : ''
										}`}
									>
										<div class="flex items-center justify-between gap-3">
											<div class="text-sm font-semibold text-text">Split feeder</div>
											{#if wizard?.discovery.recommended_camera_layout === 'split_feeder'}
												<span
													class="rounded-full bg-[#0055BF]/10 px-2 py-1 text-[11px] font-medium text-[#0055BF]"
												>
													Recommended
												</span>
											{/if}
										</div>
										<div class="mt-2 text-sm text-text-muted">
											Separate C-channel cameras plus a carousel camera.
										</div>
									</button>
								</div>
								<div class="setup-panel px-4 py-3 text-sm text-text-muted">
									Choose the layout that matches the physical camera setup on this machine.
								</div>
								<div class="flex flex-wrap items-center gap-3">
									<button
										onclick={saveLayout}
										disabled={savingLayout}
										class="setup-button-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
									>
										<Camera size={14} />
										{savingLayout ? 'Saving...' : 'Save Layout'}
									</button>
								</div>
								{#if layoutError}
									<div class="text-sm text-[#D01012]">{layoutError}</div>
								{:else if layoutStatus}
									<div class="text-sm text-[#00852B]">{layoutStatus}</div>
								{/if}
							</div>
						{:else if activeStepId === 'cameras'}
							<div class="flex flex-col gap-4">
								<div class="flex flex-wrap items-center gap-3 text-sm text-text-muted">
									<span>{usbCameras.length} USB camera(s)</span>
									<span>{networkCameras.length} network/ADB stream(s)</span>
									<button
										onclick={loadCameraInventory}
										disabled={loadingCameras}
										class="setup-button-secondary inline-flex items-center gap-2 px-3 py-1.5 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
									>
										<RefreshCcw size={14} class={loadingCameras ? 'animate-spin' : ''} />
										Refresh Sources
									</button>
								</div>

								<div class="setup-panel px-4 py-3 text-sm text-text-muted">
									Required roles must be assigned before you can continue. Optional classification
									cameras can be left empty for now.
								</div>

								<div class="grid gap-3 md:grid-cols-2">
									{#each cameraRolesForLayout() as role}
										<div class="setup-panel p-4">
											<div class="flex items-center justify-between gap-3">
												<div class="text-sm font-medium text-text">{ROLE_LABELS[role]}</div>
												<div
													class={`text-xs ${roleIsRequired(role) ? 'text-[#D01012]' : 'text-text-muted'}`}
												>
													{roleIsRequired(role) ? 'Required' : 'Optional'}
												</div>
											</div>
											<select
												value={roleSelections[role] ?? '__none__'}
												onchange={(event) =>
													handleRoleSelection(
														role,
														(event.currentTarget as HTMLSelectElement).value
													)}
												class="setup-control mt-3 w-full px-3 py-2 text-sm text-text"
											>
												{#each cameraChoices() as choice}
													<option value={choice.key}>{choice.label}</option>
												{/each}
											</select>
										</div>
									{/each}
								</div>

								<div class="flex flex-wrap items-center gap-3">
									<button
										onclick={saveCameraAssignments}
										disabled={savingAssignments}
										class="setup-button-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
									>
										<CheckCircle2 size={14} />
										{savingAssignments ? 'Saving...' : 'Save Camera Assignments'}
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
													class="inline-flex items-center justify-center border border-[#0055BF] bg-[#0055BF] px-6 py-1.5 text-xs font-medium text-white transition-colors hover:bg-[#0055BF]/90 disabled:cursor-not-allowed disabled:opacity-50"
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
						{:else if activeStepId === 'advanced'}
							<div class="flex flex-col gap-6">
								<div class="setup-panel px-4 py-3 text-sm text-text-muted">
									The baseline wizard is done at this point. This final step is where you can do
									deeper storage-layer edits and jump into the more detailed geometry or picture
									pages.
								</div>

								<div class="setup-panel px-4 py-3 text-sm">
									<div class="font-medium text-text">Current feeding mode</div>
									<div class="mt-1 text-text-muted">
										{wizard?.config.feeding.mode === 'manual_carousel'
											? 'Manual carousel feed is enabled. Operators place parts directly into the carousel dropzone.'
											: 'Automatic C-channel feeding is enabled.'}
									</div>
									<div class="mt-2 text-xs text-text-muted">
										You can change this later in General Settings. Reset and re-home after switching
										the mode.
									</div>
								</div>

								<StorageLayerSettingsSection />

								<div class="grid gap-3 md:grid-cols-2">
									<a
										href="/settings/storage-layers"
										class="setup-panel px-4 py-3 text-sm text-text transition-colors hover:bg-surface"
									>
										Open advanced storage-layer settings
									</a>
									<a
										href="/settings/chute"
										class="setup-panel px-4 py-3 text-sm text-text transition-colors hover:bg-surface"
									>
										Open chute calibration page
									</a>
									{#if selectedLayout === 'split_feeder'}
										<a
											href="/settings/c-channel-2"
											class="setup-panel px-4 py-3 text-sm text-text transition-colors hover:bg-surface"
										>
											Open C-Channel 2 settings
										</a>
										<a
											href="/settings/c-channel-3"
											class="setup-panel px-4 py-3 text-sm text-text transition-colors hover:bg-surface"
										>
											Open C-Channel 3 settings
										</a>
										<a
											href="/settings/carousel"
											class="setup-panel px-4 py-3 text-sm text-text transition-colors hover:bg-surface"
										>
											Open carousel settings
										</a>
									{/if}
									<a
										href="/settings/classification-chamber"
										class="setup-panel px-4 py-3 text-sm text-text transition-colors hover:bg-surface"
									>
										Open classification chamber settings
									</a>
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
										onclick={markCurrentStepComplete}
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
	</div>
</div>
