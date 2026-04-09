import { getContext, setContext } from 'svelte';
import type { MachineManager } from './manager.svelte';
import type { MachineContext } from './types';

const MACHINES_CONTEXT_KEY = Symbol('machines');
const MACHINE_CONTEXT_KEY = Symbol('machine');

export function setMachinesContext(manager: MachineManager): void {
	setContext(MACHINES_CONTEXT_KEY, manager);
}

export function getMachinesContext(): MachineManager {
	const ctx = getContext<MachineManager>(MACHINES_CONTEXT_KEY);
	if (!ctx) {
		throw new Error('getMachinesContext must be called within MachinesProvider');
	}
	return ctx;
}

export function setMachineContext(ctx: MachineContext): void {
	setContext(MACHINE_CONTEXT_KEY, ctx);
}

export function getMachineContext(): MachineContext {
	const ctx = getContext<MachineContext>(MACHINE_CONTEXT_KEY);
	if (!ctx) {
		throw new Error('getMachineContext must be called within MachineProvider');
	}
	return ctx;
}
