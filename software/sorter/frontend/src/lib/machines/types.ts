import type {
	CameraName,
	FrameData,
	MachineIdentityData,
	SocketEvent,
	KnownObjectData,
	KnownObjectEvent,
	CameraHealthEvent,
	RuntimeStatsEvent,
	SystemStatusEvent,
	SystemStatusData,
	SorterStateEvent,
	SorterStateData,
	CamerasConfigEvent,
	CamerasConfigData,
	SortingProfileStatusEvent,
	SortingProfileStatusData
} from '$lib/api/events';

export type MachineIdentity = MachineIdentityData;

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';

export interface MachineState {
	identity: MachineIdentity | null;
	connection: WebSocket;
	url: string | null;
	status: ConnectionStatus;
	frames: Map<CameraName, FrameData>;
	cameraHealth: Map<string, string>;
	lastHeartbeat: number | null;
	recentObjects: KnownObjectData[];
	runtimeStats: Record<string, unknown> | null;
	systemStatus: SystemStatusData | null;
	sorterState: SorterStateData | null;
	camerasConfig: CamerasConfigData | null;
	sortingProfileStatus: SortingProfileStatusData | null;
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
	readonly cameraHealth: Map<string, string>;
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

export function isCameraHealthEvent(event: SocketEvent): event is CameraHealthEvent {
	return event.tag === 'camera_health';
}

export function isRuntimeStatsEvent(event: SocketEvent): event is RuntimeStatsEvent {
	return event.tag === 'runtime_stats';
}

export function isSystemStatusEvent(event: SocketEvent): event is SystemStatusEvent {
	return event.tag === 'system_status';
}

export function isSorterStateEvent(event: SocketEvent): event is SorterStateEvent {
	return event.tag === 'sorter_state';
}

export function isCamerasConfigEvent(event: SocketEvent): event is CamerasConfigEvent {
	return event.tag === 'cameras_config';
}

export function isSortingProfileStatusEvent(
	event: SocketEvent
): event is SortingProfileStatusEvent {
	return event.tag === 'sorting_profile_status';
}
