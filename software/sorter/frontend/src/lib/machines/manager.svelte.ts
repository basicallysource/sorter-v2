import type {
	SocketEvent,
	KnownObjectData,
	CameraHealthData,
	SystemStatusData,
	SorterStateData,
	CamerasConfigData,
	SortingProfileStatusData
} from '$lib/api/events';
import type { MachineState, MachineIdentity } from './types';
import {
	isIdentityEvent,
	isHeartbeatEvent,
	isKnownObjectEvent,
	isCameraHealthEvent,
	isRuntimeStatsEvent,
	isSystemStatusEvent,
	isSorterStateEvent,
	isCamerasConfigEvent,
	isSortingProfileStatusEvent
} from './types';
import { mergeKnownObject, pieceStore } from '$lib/pieces';

const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 30000;
const CONNECTION_WATCHDOG_INTERVAL_MS = 3000;
const HEARTBEAT_STALE_MS = 15000;
const RECENT_OBJECT_BUFFER_LIMIT = 32;
const RECENT_OBJECT_REMOVAL_GRACE_MS = 1500;

function shouldKeepRecentObject(obj: KnownObjectData): boolean {
	// Aborted pieces had their classification cycle torn down before any result
	// (machine stop / reset mid-capture). Dead pieces were reaped by the backend
	// after going silent too long without ever reaching distributed. Neither will
	// progress, so drop them rather than leaving them stuck in the list.
	if (obj.aborted || obj.dead) return false;
	// Recent Pieces is a C4-only view: a piece enters the list when it is
	// first observed on the classification channel and stays until it is
	// distributed. `first_carousel_seen_ts` is set by piece_transport.py
	// the first tick a polar-tracker zone reports this piece on the
	// carousel, so it's the canonical "this piece is on / has been on C4"
	// signal. Pieces still on C2/C3 lack this stamp and are excluded.
	return obj.first_carousel_seen_ts != null;
}

export class MachineManager {
	machines = $state(new Map<string, MachineState>());
	selectedMachineId = $state<string | null>(null);
	private pending_connections = new Map<WebSocket, string>();
	private reconnect_attempts = new Map<string, number>();
	private reconnect_timers = new Map<string, ReturnType<typeof setTimeout>>();
	private ignored_closures = new WeakSet<WebSocket>();
	private recent_removal_timers = new Map<string, ReturnType<typeof setTimeout>>();
	private manually_disconnected = new Set<string>();
	private connection_watchdog_timer: ReturnType<typeof setInterval> | null = null;

	selectedMachine = $derived.by(() => {
		if (!this.selectedMachineId) return null;
		return this.machines.get(this.selectedMachineId) ?? null;
	});

	connect(url: string, options: { force?: boolean } = {}): void {
		this.manually_disconnected.delete(url);

		const existing_timer = this.reconnect_timers.get(url);
		if (existing_timer) {
			clearTimeout(existing_timer);
			this.reconnect_timers.delete(url);
		}

		if (options.force) {
			this.closeSocketsForUrl(url);
		} else if (this.hasUsableSocketForUrl(url)) {
			return;
		}

		const ws = new WebSocket(url);
		this.pending_connections.set(ws, url);

		ws.onopen = () => {
			console.log(`[MachineManager] Connected to ${url}`);
			this.reconnect_attempts.set(url, 0);
		};

		ws.onmessage = (message) => {
			const event = JSON.parse(message.data) as SocketEvent;
			this.handleEvent(ws, event);
		};

		ws.onerror = (error) => {
			console.error(`[MachineManager] WebSocket error:`, error);
		};

		ws.onclose = () => {
			console.log(`[MachineManager] WebSocket closed for ${url}`);
			const closed_url = this.pending_connections.get(ws);
			this.pending_connections.delete(ws);

			for (const [id, machine] of this.machines) {
				if (machine.connection === ws) {
					const updated = new Map(this.machines);
					const existing = updated.get(id);
					if (existing) {
						updated.set(id, { ...existing, status: 'disconnected' });
						this.machines = updated;
					}
					break;
				}
			}

			const reconnect_url = closed_url ?? url;
			if (this.ignored_closures.has(ws)) {
				return;
			}
			if (!this.manually_disconnected.has(reconnect_url)) {
				this.scheduleReconnect(reconnect_url);
			}
		};
	}

	ensureConnected(url: string, options: { respectManualDisconnect?: boolean } = {}): void {
		if (options.respectManualDisconnect !== false && this.manually_disconnected.has(url)) return;
		if (this.hasUsableSocketForUrl(url)) return;
		this.connect(url);
	}

	private scheduleReconnect(url: string): void {
		if (this.hasUsableSocketForUrl(url) || this.reconnect_timers.has(url)) {
			return;
		}
		const attempts = this.reconnect_attempts.get(url) ?? 0;
		const delay = Math.min(RECONNECT_BASE_DELAY_MS * Math.pow(2, attempts), RECONNECT_MAX_DELAY_MS);

		console.log(
			`[MachineManager] Scheduling reconnect to ${url} in ${delay}ms (attempt ${attempts + 1})`
		);

		const timer = setTimeout(() => {
			this.reconnect_timers.delete(url);
			this.reconnect_attempts.set(url, attempts + 1);
			this.connect(url);
		}, delay);

		this.reconnect_timers.set(url, timer);
	}

	startConnectionWatchdog(
		options: {
			defaultUrl?: string;
			intervalMs?: number;
			heartbeatStaleMs?: number;
		} = {}
	): () => void {
		this.stopConnectionWatchdog();
		const intervalMs = options.intervalMs ?? CONNECTION_WATCHDOG_INTERVAL_MS;
		const heartbeatStaleMs = options.heartbeatStaleMs ?? HEARTBEAT_STALE_MS;
		const defaultUrl = options.defaultUrl;

		const tick = () => {
			if (defaultUrl) {
				this.ensureConnected(defaultUrl);
			}
			this.reconnectStaleConnections({ fallbackUrl: defaultUrl, heartbeatStaleMs });
		};

		tick();
		this.connection_watchdog_timer = setInterval(tick, intervalMs);
		return () => this.stopConnectionWatchdog();
	}

	stopConnectionWatchdog(): void {
		if (this.connection_watchdog_timer === null) return;
		clearInterval(this.connection_watchdog_timer);
		this.connection_watchdog_timer = null;
	}

	reconnectStaleConnections(
		options: {
			fallbackUrl?: string;
			heartbeatStaleMs?: number;
		} = {}
	): void {
		const heartbeatStaleMs = options.heartbeatStaleMs ?? HEARTBEAT_STALE_MS;
		const now = Date.now();
		for (const machine of this.machines.values()) {
			const url = machine.url ?? options.fallbackUrl;
			if (!url) continue;
			if (this.manually_disconnected.has(url)) continue;
			if (
				machine.connection.readyState === WebSocket.CLOSING ||
				machine.connection.readyState === WebSocket.CLOSED
			) {
				this.connect(url);
				continue;
			}
			if (!this.isMachineHeartbeatStale(machine, now, heartbeatStaleMs)) continue;
			console.warn(`[MachineManager] Heartbeat stale for ${url}; reconnecting WebSocket`);
			this.connect(url, { force: true });
		}
	}

	disconnect(machineId: string): void {
		const machine = this.machines.get(machineId);
		if (machine) {
			this.clearRecentRemovalTimersForMachine(machineId);
			const url = this.findUrlBySocket(machine.connection);
			if (url) {
				this.manually_disconnected.add(url);
				const timer = this.reconnect_timers.get(url);
				if (timer) {
					clearTimeout(timer);
					this.reconnect_timers.delete(url);
				}
			}

			machine.connection.close();
			const updated = new Map(this.machines);
			updated.delete(machineId);
			this.machines = updated;
			if (this.selectedMachineId === machineId) {
				this.selectedMachineId = updated.size > 0 ? (updated.keys().next().value ?? null) : null;
			}
		}
	}

	selectMachine(machineId: string | null): void {
		this.selectedMachineId = machineId;
	}

	private findUrlBySocket(ws: WebSocket): string | null {
		for (const [socket, url] of this.pending_connections) {
			if (socket === ws) return url;
		}
		return null;
	}

	private hasUsableSocketForUrl(url: string): boolean {
		for (const [socket, socketUrl] of this.pending_connections) {
			if (socketUrl !== url) continue;
			if (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN) {
				return true;
			}
		}
		return false;
	}

	private closeSocketsForUrl(url: string): void {
		for (const [socket, socketUrl] of this.pending_connections) {
			if (socketUrl !== url) continue;
			if (socket.readyState === WebSocket.CLOSING || socket.readyState === WebSocket.CLOSED)
				continue;
			this.ignored_closures.add(socket);
			socket.close();
		}
	}

	private isMachineHeartbeatStale(
		machine: MachineState,
		nowMs: number,
		heartbeatStaleMs: number
	): boolean {
		if (machine.status !== 'connected') return false;
		if (machine.connection.readyState !== WebSocket.OPEN) return false;
		if (machine.lastHeartbeat === null) return false;
		return nowMs - machine.lastHeartbeat * 1000 > heartbeatStaleMs;
	}

	private handleEvent(ws: WebSocket, event: SocketEvent): void {
		if (isIdentityEvent(event)) {
			this.handleIdentity(ws, event.data);
		} else {
			const machineId = this.findMachineIdBySocket(ws);
			if (!machineId) {
				console.warn('[MachineManager] Received event before identity', event);
				return;
			}

			if (isHeartbeatEvent(event)) {
				this.handleHeartbeat(machineId, event.data.timestamp);
			} else if (isKnownObjectEvent(event)) {
				this.handleKnownObject(machineId, event.data);
			} else if (isCameraHealthEvent(event)) {
				this.handleCameraHealth(machineId, event.data);
			} else if (isRuntimeStatsEvent(event)) {
				this.handleRuntimeStats(machineId, event.data.payload as Record<string, unknown>);
			} else if (isSystemStatusEvent(event)) {
				this.handleSystemStatus(machineId, event.data);
			} else if (isSorterStateEvent(event)) {
				this.handleSorterState(machineId, event.data);
			} else if (isCamerasConfigEvent(event)) {
				this.handleCamerasConfig(machineId, event.data);
			} else if (isSortingProfileStatusEvent(event)) {
				this.handleSortingProfileStatus(machineId, event.data);
			}
		}
	}

	private handleIdentity(ws: WebSocket, identity: MachineIdentity): void {
		const url = this.pending_connections.get(ws);
		this.pending_connections.delete(ws);

		const existing = this.machines.get(identity.machine_id);
		const replacingConnection = Boolean(existing && existing.connection !== ws);
		if (existing && existing.connection !== ws) {
			existing.connection.close();
		}

		const updated = new Map(this.machines);
		updated.set(identity.machine_id, {
			identity,
			connection: ws,
			url: url ?? existing?.url ?? null,
			status: 'connected',
			cameraHealth: existing?.cameraHealth ?? new Map(),
			cameraFeedEpoch: (existing?.cameraFeedEpoch ?? 0) + (replacingConnection ? 1 : 0),
			lastHeartbeat: null,
			recentObjects: existing?.recentObjects ?? [],
			runtimeStats: existing?.runtimeStats ?? null,
			systemStatus: existing?.systemStatus ?? null,
			sorterState: existing?.sorterState ?? null,
			camerasConfig: existing?.camerasConfig ?? null,
			sortingProfileStatus: existing?.sortingProfileStatus ?? null
		});
		this.machines = updated;

		if (url) {
			this.pending_connections.set(ws, url);
		}

		if (!this.selectedMachineId) {
			this.selectedMachineId = identity.machine_id;
		}

		console.log(`[MachineManager] Machine identified: ${identity.machine_id}`);
	}

	refreshSelectedCameraFeeds(): void {
		const machineId = this.selectedMachineId;
		if (!machineId) return;
		const machine = this.machines.get(machineId);
		if (!machine) return;
		const updated = new Map(this.machines);
		updated.set(machineId, {
			...machine,
			cameraFeedEpoch: (machine.cameraFeedEpoch ?? 0) + 1
		});
		this.machines = updated;
	}

	private handleHeartbeat(machineId: string, timestamp: number): void {
		const machine = this.machines.get(machineId);
		if (!machine) return;

		const updated = new Map(this.machines);
		updated.set(machineId, { ...machine, lastHeartbeat: timestamp });
		this.machines = updated;
	}

	private handleKnownObject(machineId: string, obj: KnownObjectData): void {
		const machine = this.machines.get(machineId);
		if (!machine) return;

		// Every known_object event reduces into the shared piece store — the
		// records page and RecentObjects both view it. Runs before the ring's
		// early returns so dead pieces still reach the store (they exist as
		// durable records) even though the ring drops them.
		pieceStore.upsertFromWs(machineId, obj);

		// Aborted (teardown) or dead (reaped by the backend after going silent
		// too long without distributing): the piece will never progress. Drop it
		// from the buffer immediately so it can't linger.
		if (obj.aborted || obj.dead) {
			this.clearRecentRemovalTimer(machineId, obj.uuid);
			if (machine.recentObjects.some((o) => o.uuid === obj.uuid)) {
				const updated = new Map(this.machines);
				updated.set(machineId, {
					...machine,
					recentObjects: machine.recentObjects.filter((o) => o.uuid !== obj.uuid)
				});
				this.machines = updated;
			}
			return;
		}

		const existing_idx = machine.recentObjects.findIndex((o) => o.uuid === obj.uuid);
		const existing_obj = existing_idx >= 0 ? machine.recentObjects[existing_idx] : undefined;
		const merged_obj = mergeKnownObject(existing_obj, obj);
		const keep = shouldKeepRecentObject(merged_obj);
		let updated_objects: KnownObjectData[];

		if (existing_idx >= 0) {
			updated_objects = [...machine.recentObjects];
			if (keep) {
				this.clearRecentRemovalTimer(machineId, merged_obj.uuid);
				updated_objects[existing_idx] = merged_obj;
			} else {
				this.scheduleRecentRemoval(machineId, merged_obj.uuid);
				return;
			}
		} else if (keep) {
			this.clearRecentRemovalTimer(machineId, merged_obj.uuid);
			updated_objects = [merged_obj, ...machine.recentObjects].slice(0, RECENT_OBJECT_BUFFER_LIMIT);
		} else {
			return;
		}

		const updated = new Map(this.machines);
		updated.set(machineId, { ...machine, recentObjects: updated_objects });
		this.machines = updated;
	}

	private recentRemovalKey(machineId: string, uuid: string): string {
		return `${machineId}:${uuid}`;
	}

	private clearRecentRemovalTimer(machineId: string, uuid: string): void {
		const key = this.recentRemovalKey(machineId, uuid);
		const timer = this.recent_removal_timers.get(key);
		if (!timer) return;
		clearTimeout(timer);
		this.recent_removal_timers.delete(key);
	}

	private clearRecentRemovalTimersForMachine(machineId: string): void {
		for (const [key, timer] of this.recent_removal_timers) {
			if (!key.startsWith(`${machineId}:`)) continue;
			clearTimeout(timer);
			this.recent_removal_timers.delete(key);
		}
	}

	private scheduleRecentRemoval(machineId: string, uuid: string): void {
		const key = this.recentRemovalKey(machineId, uuid);
		if (this.recent_removal_timers.has(key)) return;
		const timer = setTimeout(() => {
			this.recent_removal_timers.delete(key);
			const machine = this.machines.get(machineId);
			if (!machine) return;
			const existing = machine.recentObjects.find((o) => o.uuid === uuid);
			if (!existing || shouldKeepRecentObject(existing)) return;
			const updated = new Map(this.machines);
			updated.set(machineId, {
				...machine,
				recentObjects: machine.recentObjects.filter((o) => o.uuid !== uuid)
			});
			this.machines = updated;
		}, RECENT_OBJECT_REMOVAL_GRACE_MS);
		this.recent_removal_timers.set(key, timer);
	}

	private handleCameraHealth(machineId: string, data: CameraHealthData): void {
		const machine = this.machines.get(machineId);
		if (!machine) return;
		const healthMap = new Map(Object.entries(data.cameras));
		const updated = new Map(this.machines);
		updated.set(machineId, { ...machine, cameraHealth: healthMap });
		this.machines = updated;
	}

	private handleRuntimeStats(machineId: string, payload: Record<string, unknown>): void {
		const machine = this.machines.get(machineId);
		if (!machine) return;
		const updated = new Map(this.machines);
		updated.set(machineId, { ...machine, runtimeStats: payload });
		this.machines = updated;
	}

	private handleSystemStatus(machineId: string, data: SystemStatusData): void {
		const machine = this.machines.get(machineId);
		if (!machine) return;
		const shouldClearRecentObjects =
			data.hardware_state === 'homing' ||
			(data.hardware_state === 'standby' && machine.systemStatus?.hardware_state !== 'standby');
		if (shouldClearRecentObjects) {
			this.clearRecentRemovalTimersForMachine(machineId);
			pieceStore.clearWsEntries(machineId);
		}
		const updated = new Map(this.machines);
		updated.set(machineId, {
			...machine,
			systemStatus: data,
			recentObjects: shouldClearRecentObjects ? [] : machine.recentObjects
		});
		this.machines = updated;
	}

	private handleSorterState(machineId: string, data: SorterStateData): void {
		const machine = this.machines.get(machineId);
		if (!machine) return;
		const updated = new Map(this.machines);
		updated.set(machineId, { ...machine, sorterState: data });
		this.machines = updated;
	}

	private handleCamerasConfig(machineId: string, data: CamerasConfigData): void {
		const machine = this.machines.get(machineId);
		if (!machine) return;
		const updated = new Map(this.machines);
		updated.set(machineId, { ...machine, camerasConfig: data });
		this.machines = updated;
	}

	private handleSortingProfileStatus(machineId: string, data: SortingProfileStatusData): void {
		const machine = this.machines.get(machineId);
		if (!machine) return;
		const updated = new Map(this.machines);
		updated.set(machineId, { ...machine, sortingProfileStatus: data });
		this.machines = updated;
	}

	applySystemStatusToSelected(data: SystemStatusData): void {
		const machineId = this.selectedMachineId;
		if (!machineId) return;
		this.handleSystemStatus(machineId, data);
	}

	async refreshSelectedSystemStatus(baseUrl: string): Promise<boolean> {
		try {
			const response = await fetch(`${baseUrl}/api/system/status`);
			if (!response.ok) return false;
			this.applySystemStatusToSelected((await response.json()) as SystemStatusData);
			return true;
		} catch {
			return false;
		}
	}

	queueSystemStatusRefreshes(baseUrl: string, delaysMs: number[] = [0, 500, 1500]): void {
		for (const delayMs of delaysMs) {
			window.setTimeout(() => void this.refreshSelectedSystemStatus(baseUrl), delayMs);
		}
	}

	private findMachineIdBySocket(ws: WebSocket): string | null {
		for (const [id, machine] of this.machines) {
			if (machine.connection === ws) {
				return id;
			}
		}
		return null;
	}

	sendCommand(command: unknown): void {
		const machine = this.selectedMachine;
		if (machine && machine.connection.readyState === WebSocket.OPEN) {
			machine.connection.send(JSON.stringify(command));
		}
	}

	get connectedMachines(): MachineState[] {
		return Array.from(this.machines.values()).filter((m) => m.status === 'connected');
	}
}
