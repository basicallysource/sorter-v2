import type { MachineSetupKey, StepperKey } from '$lib/settings/stations';

export type StepperPulseMode = 'duration' | 'degrees';

export type StoredStepperPulseSettings = {
	pulseMode: StepperPulseMode;
	pulseDuration: number;
	pulseSpeed: number;
	pulseDegrees: number;
};

const DEFAULT_STEPPER_PULSE_SETTINGS: StoredStepperPulseSettings = {
	pulseMode: 'duration',
	pulseDuration: 0.25,
	pulseSpeed: 800,
	pulseDegrees: 90
};

export const STEPPER_GEAR_RATIOS: Record<StepperKey, number> = {
	c_channel_1: 130 / 12,
	c_channel_2: 130 / 12,
	c_channel_3: 130 / 12,
	carousel: 1,
	chute: 120 / 25
};

export const CLASSIFICATION_CHANNEL_STEPPER_LABEL = 'Classification Channel';
export const CLASSIFICATION_CHANNEL_STEPPER_GEAR_RATIO = STEPPER_GEAR_RATIOS.c_channel_3;

export function stepperGearRatioForSetup(
	stepperKey: StepperKey,
	machineSetup?: MachineSetupKey
): number {
	if (stepperKey === 'carousel' && machineSetup === 'classification_channel') {
		return CLASSIFICATION_CHANNEL_STEPPER_GEAR_RATIO;
	}
	return STEPPER_GEAR_RATIOS[stepperKey] ?? 1;
}

export function stepperPulseStorageKey(stepperKey: StepperKey, field: string): string {
	return `stepper:${stepperKey}:${field}`;
}

export function loadStoredStepperPulseSetting<T>(
	stepperKey: StepperKey,
	field: string,
	fallback: T
): T {
	try {
		if (typeof localStorage === 'undefined') return fallback;
		const raw = localStorage.getItem(stepperPulseStorageKey(stepperKey, field));
		if (raw === null) return fallback;
		const parsed = JSON.parse(raw);
		return typeof parsed === typeof fallback ? parsed : fallback;
	} catch {
		return fallback;
	}
}

export function persistStoredStepperPulseSetting(
	stepperKey: StepperKey,
	field: string,
	value: unknown
): void {
	try {
		if (typeof localStorage === 'undefined') return;
		localStorage.setItem(stepperPulseStorageKey(stepperKey, field), JSON.stringify(value));
	} catch {
		// ignore persistence failures in the UI
	}
}

export function loadStoredStepperPulseSettings(stepperKey: StepperKey): StoredStepperPulseSettings {
	return {
		pulseMode: loadStoredStepperPulseSetting<StepperPulseMode>(
			stepperKey,
			'pulseMode',
			DEFAULT_STEPPER_PULSE_SETTINGS.pulseMode
		),
		pulseDuration: loadStoredStepperPulseSetting<number>(
			stepperKey,
			'pulseDuration',
			DEFAULT_STEPPER_PULSE_SETTINGS.pulseDuration
		),
		pulseSpeed: loadStoredStepperPulseSetting<number>(
			stepperKey,
			'pulseSpeed',
			DEFAULT_STEPPER_PULSE_SETTINGS.pulseSpeed
		),
		pulseDegrees: loadStoredStepperPulseSetting<number>(
			stepperKey,
			'pulseDegrees',
			DEFAULT_STEPPER_PULSE_SETTINGS.pulseDegrees
		)
	};
}

export async function triggerStoredStepperPulse(
	baseUrl: string,
	stepperKey: StepperKey,
	direction: 'cw' | 'ccw',
	options?: {
		gearRatio?: number;
	}
): Promise<string> {
	const settings = loadStoredStepperPulseSettings(stepperKey);

	if (settings.pulseMode === 'degrees') {
		const gearRatio = options?.gearRatio ?? STEPPER_GEAR_RATIOS[stepperKey] ?? 1;
		const motorDegrees =
			settings.pulseDegrees * gearRatio * (direction === 'ccw' ? -1 : 1);
		const params = new URLSearchParams({
			stepper: stepperKey,
			degrees: String(motorDegrees),
			speed: String(settings.pulseSpeed)
		});
		const res = await fetch(`${baseUrl}/stepper/move-degrees?${params.toString()}`, {
			method: 'POST'
		});
		if (!res.ok) {
			throw new Error(await readStepperErrorMessage(res));
		}
		return `Moving ${settings.pulseDegrees}° ${direction.toUpperCase()}.`;
	}

	const params = new URLSearchParams({
		stepper: stepperKey,
		direction,
		duration_s: String(settings.pulseDuration),
		speed: String(settings.pulseSpeed)
	});
	const res = await fetch(`${baseUrl}/stepper/pulse?${params.toString()}`, {
		method: 'POST'
	});
	if (!res.ok) {
		throw new Error(await readStepperErrorMessage(res));
	}
	return `Pulsing ${direction.toUpperCase()}.`;
}

async function readStepperErrorMessage(res: Response): Promise<string> {
	try {
		const data = await res.json();
		if (typeof data?.detail === 'string') return data.detail;
		if (typeof data?.message === 'string') return data.message;
	} catch {
		// fall through
	}
	try {
		return await res.text();
	} catch {
		return `Request failed with status ${res.status}`;
	}
}
