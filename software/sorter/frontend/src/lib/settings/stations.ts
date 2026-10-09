import Activity from '@lucide/svelte/icons/activity';
import Camera from '@lucide/svelte/icons/camera';
import CircuitBoard from '@lucide/svelte/icons/circuit-board';
import Cloud from '@lucide/svelte/icons/cloud';
import Cpu from '@lucide/svelte/icons/cpu';
import Gauge from '@lucide/svelte/icons/gauge';
import Timer from '@lucide/svelte/icons/timer';
import GitBranch from '@lucide/svelte/icons/git-branch';
import Layers3 from '@lucide/svelte/icons/layers';
import Network from '@lucide/svelte/icons/network';
import Settings from '@lucide/svelte/icons/settings';
import Shapes from '@lucide/svelte/icons/shapes';
import ShieldAlert from '@lucide/svelte/icons/shield-alert';
import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
import Wrench from '@lucide/svelte/icons/wrench';
import Zap from '@lucide/svelte/icons/zap';
import {
	CLASSIFICATION_CHANNEL_STEPPER_GEAR_RATIO,
	CLASSIFICATION_CHANNEL_STEPPER_LABEL
} from '$lib/settings/stepper-control';

export type CameraRole =
	| 'c_channel_2'
	| 'c_channel_3'
	| 'carousel'
	| 'classification_channel';

export type ZoneChannel =
	| 'second'
	| 'third'
	| 'carousel'
	| 'classification_channel';

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
	| 'classification-channel';

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
	label: 'Storage layers',
	icon: Layers3
};

export const hiveNavItem: SettingsNavItem = {
	href: '/settings/hive',
	label: 'Hive',
	icon: Cloud
};

export const hiveModelsNavItem: SettingsNavItem = {
	href: '/settings/hive/models',
	label: 'Local models',
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
	label: 'Control board',
	icon: CircuitBoard
};

export const chuteAimingNavItem: SettingsNavItem = {
	href: '/settings/chute-aiming',
	label: 'Chute aiming',
	icon: Shapes
};

export const stallguardNavItem: SettingsNavItem = {
	href: '/settings/stepper-stallguard',
	label: 'StallGuard',
	icon: Activity
};

export const jitterTestNavItem: SettingsNavItem = {
	href: '/settings/jitter-test',
	label: 'Jitter test',
	icon: Zap
};

export const performanceNavItem: SettingsNavItem = {
	href: '/settings/performance',
	label: 'Performance',
	icon: Gauge
};

export const cycleTimeNavItem: SettingsNavItem = {
	href: '/settings/cycle-time',
	label: 'Cycle time',
	icon: Timer
};

export const incidentsNavItem: SettingsNavItem = {
	href: '/settings/incidents',
	label: 'Incidents',
	icon: ShieldAlert
};

export const powerStressNavItem: SettingsNavItem = {
	href: '/settings/power-stress',
	label: 'Power stress test',
	icon: Zap
};

export const tuningNavItems: SettingsNavItem[] = [
	{
		href: '/settings/tuning/feeder-pulse-perception',
		label: 'Feeder simple pulse',
		icon: SlidersHorizontal
	},
	{
		href: '/settings/tuning/classification-channel',
		label: 'Classification channel',
		icon: SlidersHorizontal
	},
	{
		href: '/settings/tuning/object-tracker',
		label: 'Object tracker',
		icon: SlidersHorizontal
	},
	{
		href: '/settings/tuning/piece-link',
		label: 'Piece link (experimental)',
		icon: SlidersHorizontal
	}
];

export const stationPageConfigs: StationPageConfig[] = [
	{
		slug: 'c-channel-1',
		href: '/settings/c-channel-1',
		label: 'C-channel 1',
		icon: Wrench,
		description: 'Bulk feed channel. This station only exposes manual stepper control.',
		cameraRoles: [],
		zoneChannels: [],
		stepperKeys: ['c_channel_1']
	},
	{
		slug: 'c-channel-2',
		href: '/settings/c-channel-2',
		label: 'C-channel 2',
		icon: Camera,
		description: 'Configure the second feeder camera, zone geometry, and rotor stepper controls.',
		cameraRoles: ['c_channel_2'],
		zoneChannels: ['second'],
		stepperKeys: ['c_channel_2']
	},
	{
		slug: 'c-channel-3',
		href: '/settings/c-channel-3',
		label: 'C-channel 3',
		icon: Camera,
		description: 'Configure the third feeder camera, zone geometry, and rotor stepper controls.',
		cameraRoles: ['c_channel_3'],
		zoneChannels: ['third'],
		stepperKeys: ['c_channel_3']
	},
	{
		slug: 'classification-channel',
		href: '/settings/classification-channel',
		label: 'Classification channel',
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
	}
];

export type SettingsNavHeading = {
	type: 'heading';
	label: string;
};

export type SettingsNavEntry = SettingsNavItem | SettingsNavHeading;

export const settingsNavItems: SettingsNavEntry[] = [
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
	cycleTimeNavItem,
	powerStressNavItem,
	chuteAimingNavItem,
	stallguardNavItem,
	jitterTestNavItem,
	performanceNavItem,
	{ type: 'heading', label: 'Tuning' },
	...tuningNavItems
];

// The same entries as the side nav's groups: each heading starts a group.
export const settingsNavGroups: { label?: string; items: SettingsNavItem[] }[] =
	settingsNavItems.reduce<{ label?: string; items: SettingsNavItem[] }[]>(
		(groups, entry) => {
			if ('href' in entry) groups[groups.length - 1].items.push(entry);
			else groups.push({ label: entry.label, items: [] });
			return groups;
		},
		[{ items: [] }]
	);


export function getStationPageConfig(slug: string): StationPageConfig | undefined {
	return stationPageConfigs.find((station) => station.slug === slug);
}

export const stepperLabels: Record<StepperKey, string> = {
	c_channel_1: 'C-channel 1',
	c_channel_2: 'C-channel 2',
	c_channel_3: 'C-channel 3',
	c_channel_4: 'C-channel 4',
	carousel: CLASSIFICATION_CHANNEL_STEPPER_LABEL,
	chute: 'Chute'
};
