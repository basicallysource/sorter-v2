import {
	Activity,
	Camera,
	CircuitBoard,
	Cloud,
	Cpu,
	Gauge,
	GitBranch,
	Layers3,
	Network,
	Settings,
	Shapes,
	ShieldAlert,
	SlidersHorizontal,
	Wrench,
	Zap
} from 'lucide-svelte';
import {
	CLASSIFICATION_CHANNEL_STEPPER_GEAR_RATIO,
	CLASSIFICATION_CHANNEL_STEPPER_LABEL
} from '$lib/settings/stepper-control';

export type MachineSetupKey = 'classification_channel' | 'manual_carousel';

export type CameraRole =
	| 'c_channel_2'
	| 'c_channel_3'
	| 'carousel'
	| 'classification_channel'
	| 'classification_top'
	| 'classification_bottom';

export type ZoneChannel =
	| 'second'
	| 'third'
	| 'carousel'
	| 'classification_channel'
	| 'class_top'
	| 'class_bottom';

export type StepperKey =
	| 'c_channel_1'
	| 'c_channel_2'
	| 'c_channel_3'
	| 'c_channel_4'
	| 'carousel'
	| 'chute';

export type EndstopConfig = {
	configEndpoint: string;
	liveEndpoint: string;
	homeEndpoint: string;
	homeCancelEndpoint: string;
	calibrateEndpoint?: string;
};

export type StationSlug =
	| 'c-channel-1'
	| 'c-channel-2'
	| 'c-channel-3'
	| 'carousel'
	| 'classification-channel'
	| 'classification-chamber';

export type SettingsNavItem = {
	href: string;
	label: string;
	icon: typeof Settings;
};

export type StationPageConfig = SettingsNavItem & {
	slug: StationSlug;
	description: string;
	cameraRoles: CameraRole[];
	zoneChannels: ZoneChannel[];
	stepperKeys: StepperKey[];
	stepperEndstops?: Partial<Record<StepperKey, EndstopConfig>>;
	stepperDisplay?: Partial<Record<StepperKey, { label?: string; gearRatio?: number }>>;
};

export const generalNavItem: SettingsNavItem = {
	href: '/settings',
	label: 'General',
	icon: Settings
};

export const storageLayersNavItem: SettingsNavItem = {
	href: '/settings/storage-layers',
	label: 'Storage Layers',
	icon: Layers3
};

export const hiveNavItem: SettingsNavItem = {
	href: '/settings/hive',
	label: 'Hive',
	icon: Cloud
};

export const hiveModelsNavItem: SettingsNavItem = {
	href: '/settings/hive/models',
	label: 'Local Models',
	icon: Cpu
};

export const classificationProvidersNavItem: SettingsNavItem = {
	href: '/settings/providers',
	label: 'Providers',
	icon: Network
};

export const versionsNavItem: SettingsNavItem = {
	href: '/settings/versions',
	label: 'Versions',
	icon: GitBranch
};

export const chuteNavItem: SettingsNavItem = {
	href: '/settings/chute',
	label: 'Chute',
	icon: Wrench
};

export const controlBoardNavItem: SettingsNavItem = {
	href: '/settings/control-board',
	label: 'Control Board',
	icon: CircuitBoard
};

export const chuteAimingNavItem: SettingsNavItem = {
	href: '/settings/chute-aiming',
	label: 'Chute Aiming',
	icon: Shapes
};

export const stallguardNavItem: SettingsNavItem = {
	href: '/settings/stepper-stallguard',
	label: 'StallGuard',
	icon: Activity
};

export const jitterTestNavItem: SettingsNavItem = {
	href: '/settings/jitter-test',
	label: 'Jitter Test',
	icon: Zap
};

export const performanceNavItem: SettingsNavItem = {
	href: '/settings/performance',
	label: 'Performance',
	icon: Gauge
};

export const incidentsNavItem: SettingsNavItem = {
	href: '/settings/incidents',
	label: 'Incidents',
	icon: ShieldAlert
};

export const tuningNavItems: SettingsNavItem[] = [
	{
		href: '/settings/tuning/feeder-go-to-angle',
		label: 'Feeder Go-To-Angle',
		icon: SlidersHorizontal
	},
	{
		href: '/settings/tuning/feeder-pulse-perception',
		label: 'Feeder Simple Pulse',
		icon: SlidersHorizontal
	},
	{
		href: '/settings/tuning/feeder-constant-movement',
		label: 'Feeder Constant Movement',
		icon: SlidersHorizontal
	},
	{
		href: '/settings/tuning/classification-channel',
		label: 'Classification Channel',
		icon: SlidersHorizontal
	},
	{
		href: '/settings/tuning/upstream-match',
		label: 'Upstream Match',
		icon: SlidersHorizontal
	},
	{
		href: '/settings/tuning/object-tracker',
		label: 'Object Tracker',
		icon: SlidersHorizontal
	}
];

export const stationPageConfigs: StationPageConfig[] = [
	{
		slug: 'c-channel-1',
		href: '/settings/c-channel-1',
		label: 'C-Channel 1',
		icon: Wrench,
		description: 'Bulk feed channel. This station only exposes manual stepper control.',
		cameraRoles: [],
		zoneChannels: [],
		stepperKeys: ['c_channel_1']
	},
	{
		slug: 'c-channel-2',
		href: '/settings/c-channel-2',
		label: 'C-Channel 2',
		icon: Camera,
		description: 'Configure the second feeder camera, zone geometry, and rotor stepper controls.',
		cameraRoles: ['c_channel_2'],
		zoneChannels: ['second'],
		stepperKeys: ['c_channel_2']
	},
	{
		slug: 'c-channel-3',
		href: '/settings/c-channel-3',
		label: 'C-Channel 3',
		icon: Camera,
		description: 'Configure the third feeder camera, zone geometry, and rotor stepper controls.',
		cameraRoles: ['c_channel_3'],
		zoneChannels: ['third'],
		stepperKeys: ['c_channel_3']
	},
	{
		slug: 'carousel',
		href: '/settings/carousel',
		label: 'Carousel',
		icon: Shapes,
		description: 'Configure the carousel camera, carousel polygon, and carousel stepper.',
		cameraRoles: ['carousel'],
		zoneChannels: ['carousel'],
		stepperKeys: ['carousel'],
		stepperEndstops: {
			carousel: {
				configEndpoint: '/api/hardware-config/carousel',
				liveEndpoint: '/api/hardware-config/carousel/live',
				homeEndpoint: '/api/hardware-config/carousel/home',
				homeCancelEndpoint: '/api/hardware-config/carousel/home/cancel'
			}
		}
	},
	{
		slug: 'classification-channel',
		href: '/settings/classification-channel',
		label: 'Classification C-Channel (C4)',
		icon: Camera,
		description:
			'Configure the fourth C-channel camera, arc zones, and classification-channel stepper.',
		cameraRoles: ['classification_channel'],
		zoneChannels: ['classification_channel'],
		stepperKeys: ['c_channel_4'],
		stepperDisplay: {
			c_channel_4: {
				label: CLASSIFICATION_CHANNEL_STEPPER_LABEL,
				gearRatio: CLASSIFICATION_CHANNEL_STEPPER_GEAR_RATIO
			}
		}
	},
	{
		slug: 'classification-chamber',
		href: '/settings/classification-chamber',
		label: 'Classification Chamber',
		icon: Camera,
		description:
			'Manage the classification chamber cameras and crop zones. Camera tuning controls are not exposed by the backend yet.',
		cameraRoles: ['classification_top', 'classification_bottom'],
		zoneChannels: ['class_top', 'class_bottom'],
		stepperKeys: []
	}
];

export type SettingsNavHeading = {
	type: 'heading';
	label: string;
};

export type SettingsNavEntry = SettingsNavItem | SettingsNavHeading;

const baseSettingsNavItems: SettingsNavEntry[] = [
	generalNavItem,
	hiveNavItem,
	hiveModelsNavItem,
	classificationProvidersNavItem,
	versionsNavItem,
	{ type: 'heading', label: 'Hardware' },
	...stationPageConfigs,
	chuteNavItem,
	storageLayersNavItem,
	controlBoardNavItem,
	{ type: 'heading', label: 'Helpers' },
	incidentsNavItem,
	chuteAimingNavItem,
	stallguardNavItem,
	jitterTestNavItem,
	performanceNavItem,
	{ type: 'heading', label: 'Tuning' },
	...tuningNavItems
];

export function settingsNavItemsForSetup(setup: MachineSetupKey): SettingsNavEntry[] {
	const hiddenSlugs =
		setup === 'classification_channel'
			? new Set<StationSlug>(['carousel', 'classification-chamber'])
			: new Set<StationSlug>(['classification-channel']);

	return baseSettingsNavItems.filter((entry) => {
		if (!('href' in entry)) return true;
		const station = stationPageConfigs.find((candidate) => candidate.href === entry.href);
		if (!station) return true;
		return !hiddenSlugs.has(station.slug);
	});
}

export const settingsNavItems: SettingsNavEntry[] =
	settingsNavItemsForSetup('classification_channel');

export function getStationPageConfig(slug: string): StationPageConfig | undefined {
	return stationPageConfigs.find((station) => station.slug === slug);
}

export const stepperLabels: Record<StepperKey, string> = {
	c_channel_1: 'C Channel 1',
	c_channel_2: 'C Channel 2',
	c_channel_3: 'C Channel 3',
	c_channel_4: 'C Channel 4',
	carousel: 'Carousel',
	chute: 'Chute'
};
