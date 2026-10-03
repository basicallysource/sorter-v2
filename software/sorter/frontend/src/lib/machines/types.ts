import type { Machine } from './manager.svelte';

export type MachineState = Machine;

export interface MachineContext {
	readonly machine: MachineState | null;
	readonly cameraHealth: Map<string, string>;
}
