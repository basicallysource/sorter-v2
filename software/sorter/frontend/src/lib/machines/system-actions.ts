// The System menu's hardware actions (AppHeader), in one place, for any page
// that offers one where it is needed: Home, and Start without homing. Each
// answers at once; the work goes on in the background and its progress comes
// through the machine's system status, kept fresh here.

import {
	getBackendHttpBase,
	getBackendWsBase,
	machineHttpBaseUrlFromWsUrl,
	machineWsUrlFromHttpBaseUrl
} from '$lib/backend';
import type { MachineManager } from './manager.svelte';

export function selectedBaseUrl(manager: MachineManager): string {
	return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? getBackendHttpBase();
}

function keepSystemStatusFresh(manager: MachineManager, baseUrl: string): void {
	const wsUrl =
		machineWsUrlFromHttpBaseUrl(baseUrl) ?? manager.selectedMachine?.url ?? `${getBackendWsBase()}/ws`;
	manager.ensureConnected(wsUrl);
	manager.queueSystemStatusRefreshes(baseUrl);
}

async function runSystemAction(
	manager: MachineManager,
	path: string,
	fallbackState: string,
	fallbackStep: string
): Promise<void> {
	const baseUrl = selectedBaseUrl(manager);
	try {
		const response = await fetch(`${baseUrl}${path}`, { method: 'POST' });
		const payload = (await response.json().catch(() => null)) as Record<string, unknown> | null;
		const state =
			typeof payload?.hardware_state === 'string' ? payload.hardware_state : fallbackState;
		const step = typeof payload?.message === 'string' ? payload.message : fallbackStep;
		manager.applySystemStatusToSelected({
			hardware_state: state,
			hardware_error: null,
			homing_step: state === 'homing' || state === 'initializing' ? step : null,
			no_power_development_mode:
				manager.selectedMachine?.systemStatus?.no_power_development_mode ?? false
		});
	} catch {
		// The status refreshes below show what the machine did.
	}
	keepSystemStatusFresh(manager, baseUrl);
}

// Starts the hardware if it is not, and homes the machine.
export function homeSelectedMachine(manager: MachineManager): Promise<void> {
	return runSystemAction(manager, '/api/system/recover', 'homing', 'Starting safe recovery...');
}

// Powers the motors and opens the boards without homing anything.
export function startSelectedMachine(manager: MachineManager): Promise<void> {
	return runSystemAction(manager, '/api/system/initialize', 'initializing', 'Starting the hardware...');
}
