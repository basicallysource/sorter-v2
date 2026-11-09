// The setup summary (backend server/routers/setup.py): the machine, its
// hardware's state, what is configured, what was found, and what is ready.
// Plus the few calls the setup flow makes that belong to no other module.

import type { HardwareErrorData } from '$lib/api/events';
import type { ChuteSettings } from './chute';
import { getJson, postJson } from './http';

// A control board that answered.
export type FoundBoard = {
	family: string;
	role: string;
	// What its firmware says it is (basically_v1_5, skr_pico, ...).
	hw_id: string;
	device_name: string;
	port: string;
	address: number;
	// The motors it drives, by their names on the board.
	logical_steppers: string[];
	// PWM servos on the board.
	servo_count: number;
	input_aliases: Record<string, number>;
	// It turns the doors with serial servos on a bus of its own.
	servo_bus: boolean;
	// Its firmware watches those servos; one that does not is too old to move them.
	servo_guard: boolean;
	// The kind of chute it is made for, when it is made for one.
	chute_variant: string | null;
};

export type UsbDevice = {
	device: string;
	product: string;
	serial: string | null;
	vid_pid: string | null;
	category: 'controller' | 'servo_bus' | 'unrecognised_controller' | 'unknown';
	use_by_default: boolean;
	detail: string;
	family?: string | null;
	role?: string | null;
	device_name?: string | null;
	logical_steppers?: string[];
	servo_count?: number;
};

export type MotorDirection = {
	name: string;
	label: string;
	inverted: boolean;
	live_inverted: boolean | null;
	available: boolean;
};

// 'bus': serial servos on the control board's own bus (set up on the doors
// page); 'waveshare': serial servos on a USB adapter; 'pca9685': PWM servos.
export type ServoBackend = 'bus' | 'waveshare' | 'pca9685';

export type DoorsSummary = {
	layer_count: number;
	// The layer whose door has no servo and is always shut, counted from 0.
	fixed_layer: number | null;
	// Doors that need a servo set up, and how many are.
	needed: number;
	set_up: number;
};

export type Readiness = {
	machine_named: boolean;
	// A board answered and every motor is on one.
	boards_detected: boolean;
	cameras_assigned: boolean;
	servo_configured: boolean;
	// The pieces no bin takes have somewhere to go.
	discard_ready: boolean;
	// The chute has found its home since the machine was last started.
	chute_homed: boolean;
	// The machine is homed and ready to run.
	ready_for_motion_test: boolean;
};

export type HardwareState = 'standby' | 'initializing' | 'initialized' | 'homing' | 'ready' | 'error' | string;

export type SetupSummary = {
	machine: { machine_id: string; nickname: string | null };
	hardware: {
		state: HardwareState;
		error: HardwareErrorData | null;
		homing_step: string | null;
	};
	config: {
		camera_assignments: Record<string, number | string | null>;
		servo: { backend: ServoBackend; layer_count: number; port: string | null };
		chute: ChuteSettings;
		doors: DoorsSummary;
		stepper_directions: MotorDirection[];
	};
	discovery: {
		// live, cached, scan, scan_error, skipped or unavailable.
		source: string;
		scanned_at_ms: number;
		boards: FoundBoard[];
		missing_required_steppers: string[];
		pca_available: boolean;
		usb_devices: UsbDevice[];
		// A board with no firmware, showing up as its boot drive.
		bootloader_board: boolean;
		issues: string[];
	};
	readiness: Readiness;
};

export function getSetupSummary(base: string, signal?: AbortSignal): Promise<SetupSummary> {
	return getJson<SetupSummary>(base, '/api/setup-wizard', { signal });
}

export function saveMachineName(base: string, nickname: string | null): Promise<unknown> {
	return postJson(base, '/api/machine-identity', { nickname });
}

export function setMotorInverted(
	base: string,
	name: string,
	inverted: boolean
): Promise<{ ok: true; inverted: boolean; applied_live: boolean; steppers: MotorDirection[] }> {
	return postJson(base, `/api/setup-wizard/stepper-directions/${encodeURIComponent(name)}`, { inverted });
}

export type HiveTarget = {
	id: string;
	name: string;
	url: string;
	machine_id: string | null;
	enabled: boolean;
};

// The Hives this sorter is connected to.
export async function getHiveTargets(base: string): Promise<HiveTarget[]> {
	const payload = await getJson<{ targets?: Partial<HiveTarget>[] }>(base, '/api/settings/hive');
	const raw = Array.isArray(payload?.targets) ? payload.targets : [];
	return raw.map((entry, index) => ({
		id: entry.id?.trim() ? entry.id : `target-${index + 1}`,
		name: entry.name?.trim() ? entry.name : (entry.url ?? `Hive ${index + 1}`),
		url: entry.url ?? '',
		machine_id: entry.machine_id ?? null,
		enabled: Boolean(entry.enabled)
	}));
}

// The Hive among them that is the official one, if it is connected.
export function officialHive(targets: HiveTarget[], officialUrl: string): HiveTarget | null {
	const host = (url: string) => {
		try {
			return new URL(url).host;
		} catch {
			return url.replace(/\/$/, '');
		}
	};
	return targets.find((target) => host(target.url) === host(officialUrl)) ?? null;
}

// Turns a motor a little, a quarter of a second at a slow speed.
export function jogMotor(base: string, name: string, direction: 'cw' | 'ccw'): Promise<unknown> {
	return postJson(base, '/stepper/pulse', undefined, {
		query: { stepper: name, direction, duration_s: 0.25, speed: 600 }
	});
}
