import type { HardwareErrorData } from '$lib/api/events';
export type DiscoveredBoard = {
	family: string;
	role: string;
	device_name: string;
	port: string;
	address: number;
	logical_steppers: string[];
	servo_count: number;
	input_aliases: Record<string, number>;
};

export type WavesharePort = {
	device: string;
	product: string;
	serial: string | null;
};

export type UsbDeviceCategory = 'controller' | 'servo_bus' | 'unrecognised_controller' | 'unknown';

export type UsbDevice = {
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

export type StepperDirectionEntry = {
	name: string;
	label: string;
	inverted: boolean;
	live_inverted: boolean | null;
	available: boolean;
};

export type WizardSummary = {
	machine: {
		machine_id: string;
		nickname: string | null;
	};
	hardware: {
		state: string;
		error: HardwareErrorData | null;
		homing_step: string | null;
	};
	config: {
		camera_assignments: Record<string, number | string | null>;
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
		bootloader_board: boolean;
		issues: string[];
	};
	readiness: Record<string, boolean>;
};

export type HiveSetupTarget = {
	id: string;
	name: string;
	url: string;
	machine_id: string | null;
	enabled: boolean;
};
