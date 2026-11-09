// Starting the hardware (backend server/routers/system.py). Both calls answer
// at once and the work goes on in the background; its progress comes through
// the machine's system status. A machine already busy with another start says
// so, and that comes back as an ApiError like any other failure.

import { postJson } from './http';

type Started = { ok: true; hardware_state: string; message: string };

// Powers the motors and opens the boards without homing anything.
export function startHardware(base: string): Promise<Started> {
	return postJson<Started>(base, '/api/system/initialize');
}

// Stops the hardware and puts the machine in standby; it answers when done.
export function stopHardware(base: string): Promise<Started> {
	return postJson<Started>(base, '/api/system/reset');
}

// Starts the hardware and homes the machine, ready to sort.
export function homeMachine(base: string): Promise<Started> {
	return postJson<Started>(base, '/api/system/home');
}
