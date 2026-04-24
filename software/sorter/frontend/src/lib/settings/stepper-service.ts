import type { StepperKey } from '$lib/settings/stations';

export type StepperDirection = 'cw' | 'ccw';
export type StepperDriverMode = 'off' | 'stealthchop' | 'coolstep';

export type StepperTmcPayload = {
	irun: number;
	ihold: number;
	microsteps: number;
	driver_mode: StepperDriverMode;
};

function apiBase(baseUrl: string): string {
	return baseUrl.replace(/\/$/, '');
}

export async function readStepperErrorMessage(res: Response): Promise<string> {
	try {
		const data = await res.json();
		if (typeof data?.detail === 'string') return data.detail;
		if (typeof data?.message === 'string') return data.message;
	} catch {
		/* fall through */
	}
	try {
		return await res.text();
	} catch {
		return `Request failed with status ${res.status}`;
	}
}

async function parseJsonResponse<T>(res: Response): Promise<T> {
	if (!res.ok) throw new Error(await readStepperErrorMessage(res));
	return (await res.json()) as T;
}

export async function loadStepperDirections(baseUrl: string): Promise<any> {
	const res = await fetch(`${apiBase(baseUrl)}/api/setup-wizard/stepper-directions`);
	return parseJsonResponse<any>(res);
}

export async function saveStepperDirection(
	baseUrl: string,
	stepperKey: StepperKey,
	inverted: boolean
): Promise<any> {
	const res = await fetch(`${apiBase(baseUrl)}/api/setup-wizard/stepper-directions/${stepperKey}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ inverted })
	});
	return parseJsonResponse<any>(res);
}

export async function loadStepperEndpoint(baseUrl: string, endpoint: string): Promise<any> {
	const res = await fetch(`${apiBase(baseUrl)}${endpoint}`);
	return parseJsonResponse<any>(res);
}

export async function postStepperEndpoint(
	baseUrl: string,
	endpoint: string,
	options: { payload?: unknown; signal?: AbortSignal } = {}
): Promise<any> {
	const res = await fetch(`${apiBase(baseUrl)}${endpoint}`, {
		method: 'POST',
		headers: options.payload === undefined ? undefined : { 'Content-Type': 'application/json' },
		body: options.payload === undefined ? undefined : JSON.stringify(options.payload),
		signal: options.signal
	});
	return parseJsonResponse<any>(res);
}

export async function pulseStepper(
	baseUrl: string,
	stepperKey: StepperKey,
	direction: StepperDirection,
	options: { durationSeconds: number; speed: number }
): Promise<void> {
	const params = new URLSearchParams({
		stepper: stepperKey,
		direction,
		duration_s: String(options.durationSeconds),
		speed: String(options.speed)
	});
	const res = await fetch(`${apiBase(baseUrl)}/stepper/pulse?${params.toString()}`, {
		method: 'POST'
	});
	if (!res.ok) throw new Error(await readStepperErrorMessage(res));
}

export async function moveStepperDegrees(
	baseUrl: string,
	stepperKey: StepperKey,
	options: { motorDegrees: number; speed: number }
): Promise<void> {
	const params = new URLSearchParams({
		stepper: stepperKey,
		degrees: String(options.motorDegrees),
		speed: String(options.speed)
	});
	const res = await fetch(`${apiBase(baseUrl)}/stepper/move-degrees?${params.toString()}`, {
		method: 'POST'
	});
	if (!res.ok) throw new Error(await readStepperErrorMessage(res));
}

export async function stopStepperMotion(baseUrl: string, stepperKey: StepperKey): Promise<void> {
	const params = new URLSearchParams({ stepper: stepperKey });
	const res = await fetch(`${apiBase(baseUrl)}/stepper/stop?${params.toString()}`, {
		method: 'POST'
	});
	if (!res.ok) throw new Error(await readStepperErrorMessage(res));
}

export async function loadStepperTmcSettings(
	baseUrl: string,
	stepperKey: StepperKey
): Promise<any> {
	const res = await fetch(`${apiBase(baseUrl)}/api/stepper/${stepperKey}/tmc`);
	return parseJsonResponse<any>(res);
}

export async function saveStepperTmcSettings(
	baseUrl: string,
	stepperKey: StepperKey,
	payload: StepperTmcPayload
): Promise<any> {
	const res = await fetch(`${apiBase(baseUrl)}/api/stepper/${stepperKey}/tmc`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
	return parseJsonResponse<any>(res);
}
