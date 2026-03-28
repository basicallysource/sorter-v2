import { Camera, Layers3, Settings, Shapes, Wrench } from 'lucide-svelte';

export type CameraRole =
	| 'c_channel_2'
	| 'c_channel_3'
	| 'carousel'
	| 'classification_top'
	| 'classification_bottom';

export type ZoneChannel = 'second' | 'third' | 'carousel' | 'class_top' | 'class_bottom';

export type StepperKey = 'c_channel_1' | 'c_channel_2' | 'c_channel_3' | 'carousel' | 'chute';

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

export const chuteNavItem: SettingsNavItem = {
	href: '/settings/chute',
	label: 'Chute',
	icon: Wrench
};

export const stationPageConfigs: StationPageConfig[] = [
	{
		slug: 'c-channel-1',
		href: '/settings/c-channel-1',
		label: 'C-Channel 1',
		icon: Wrench,
		description:
			'Bulk feed channel. This station only exposes manual stepper control.',
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
				homeCancelEndpoint: '/api/hardware-config/carousel/home/cancel',
				calibrateEndpoint: '/api/hardware-config/carousel/calibrate'
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

export const settingsNavItems: SettingsNavItem[] = [
	generalNavItem,
	storageLayersNavItem,
	chuteNavItem,
	...stationPageConfigs
];

export function getStationPageConfig(slug: string): StationPageConfig | undefined {
	return stationPageConfigs.find((station) => station.slug === slug);
}

export const stepperLabels: Record<StepperKey, string> = {
	c_channel_1: 'C Channel 1',
	c_channel_2: 'C Channel 2',
	c_channel_3: 'C Channel 3',
	carousel: 'Carousel',
	chute: 'Chute'
};
