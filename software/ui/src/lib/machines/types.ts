import type {
	CameraName,
	FrameData,
	MachineIdentityData,
	SocketEvent,
	KnownObjectData,
	KnownObjectEvent
} from '$lib/api/events';

export type MachineIdentity = MachineIdentityData;

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';

export interface MachineState {
	identity: MachineIdentity | null;
	connection: WebSocket;
	status: ConnectionStatus;
	frames: Map<CameraName, FrameData>;
	lastHeartbeat: number | null;
	recentObjects: KnownObjectData[];
}

export interface MachinesContext {
	readonly machines: Map<string, MachineState>;
	readonly selectedMachineId: string | null;
	readonly selectedMachine: MachineState | null;
	connect(url: string): void;
	disconnect(machineId: string): void;
	selectMachine(machineId: string | null): void;
}

export interface MachineContext {
	readonly machine: MachineState | null;
	readonly frames: Map<CameraName, FrameData>;
	sendCommand(command: unknown): void;
}

export function isIdentityEvent(
	event: SocketEvent
): event is { tag: 'identity'; data: MachineIdentity } {
	return event.tag === 'identity';
}

export function isFrameEvent(event: SocketEvent): event is { tag: 'frame'; data: FrameData } {
	return event.tag === 'frame';
}

export function isHeartbeatEvent(
	event: SocketEvent
): event is { tag: 'heartbeat'; data: { timestamp: number } } {
	return event.tag === 'heartbeat';
}

export function isKnownObjectEvent(event: SocketEvent): event is KnownObjectEvent {
	return event.tag === 'known_object';
}
