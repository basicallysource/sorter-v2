// What each motor's driver reports, as the backend records it all the time,
// whether the motor moves or not and whether stall detection is on or not
// (GET /api/drivers and /api/drivers/{name}/history). A motor's name here is
// the one /api/stepper/{name}/tmc takes.

import { getJson } from './http';

// One reading of a driver.
export type DriverSample = {
	// When it was read, in seconds since the epoch, by the machine's clock.
	t: number;
	moving: boolean;
	// CS_ACTUAL: the current the driver put out at that moment, 0 to 31.
	cs_actual: number;
	// SG_RESULT: the load, 0 to 510, lower when loaded. It only means something
	// while the motor moves.
	sg_result: number | null;
	full_steps_per_s: number | null;
	// PWM_SCALE_SUM: how much of its voltage the driver is using, 0 to 255.
	pwm_scale_sum: number | null;
	pwm_scale_auto: number | null;
	// PWM_OFS_AUTO and PWM_GRAD_AUTO: what the driver's automatic tuning settled on.
	pwm_ofs_auto: number | null;
	pwm_grad_auto: number | null;
	// The driver's heat warning, before it shuts down.
	overheating: boolean;
	overheated: boolean;
	short: boolean;
	shut_down: boolean;
};

export type DriverFaultKind = 'shut_down' | 'overheated' | 'overheating' | 'tuning_out_of_range';

// What is wrong with a driver now, in a sentence written for the person at the machine.
export type DriverFault = {
	kind: DriverFaultKind;
	since: number;
	detail: string;
};

// Something the machine did to get a driver working again, and whether it worked.
export type DriverRecovery = {
	t: number;
	what: string;
	ok: boolean;
};

export type DriverState = {
	name: string;
	label: string;
	latest: DriverSample | null;
	fault: DriverFault | null;
	recoveries: DriverRecovery[];
};

// `enabled` is false on a machine whose driver record is switched off.
export type DriverList = {
	enabled: boolean;
	drivers: DriverState[];
};

export type DriverHistory = {
	enabled: boolean;
	name: string;
	// Oldest first, at most about 1,200 however long the time asked for.
	samples: DriverSample[];
};

export function getDrivers(base: string, signal?: AbortSignal): Promise<DriverList> {
	return getJson<DriverList>(base, '/api/drivers', { signal });
}

// A motor's readings over the last `seconds`.
export function getDriverHistory(
	base: string,
	name: string,
	seconds: number,
	signal?: AbortSignal
): Promise<DriverHistory> {
	return getJson<DriverHistory>(base, `/api/drivers/${encodeURIComponent(name)}/history`, {
		query: { seconds },
		signal
	});
}
