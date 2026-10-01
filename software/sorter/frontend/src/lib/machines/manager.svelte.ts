import type {
	SocketEvent,
	KnownObjectData,
	MachineIdentityData,
	SystemStatusData,
	SorterStateData,
	CamerasConfigData,
	SortingProfileStatusData
} from '$lib/api/events';
import { mergeKnownObject, pieceStore } from '$lib/pieces';

const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 3000;
const CONNECTION_WATCHDOG_INTERVAL_MS = 1000;
// The server sends a heartbeat every 2 s. A connection silent for this long is
// dead even if the browser still calls it open (a sleeping laptop, a dropped
// Wi-Fi link, a server that gave up on a slow client).
const STALE_MS = 5000;
const RECENT_OBJECT_BUFFER_LIMIT = 32;
const RECENT_OBJECT_REMOVAL_GRACE_MS = 1500;

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';

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

/** One sorter as its websocket reports it. Each field is its own reactive
 *  value, so an event re-runs only what reads the field it changed. */
export class Machine {
	id: string;
	connection: WebSocket;
	identity = $state.raw<MachineIdentityData | null>(null);
	url = $state<string | null>(null);
	status = $state<ConnectionStatus>('connected');
	cameraHealth = $state.raw(new Map<string, string>());
	recentObjects = $state.raw<KnownObjectData[]>([]);
	runtimeStats = $state.raw<Record<string, unknown> | null>(null);
	systemStatus = $state.raw<SystemStatusData | null>(null);
	sorterState = $state.raw<SorterStateData | null>(null);
	camerasConfig = $state.raw<CamerasConfigData | null>(null);
	sortingProfileStatus = $state.raw<SortingProfileStatusData | null>(null);
	// Pieces that no longer belong in the ring leave it after a grace period.
	removalTimers = new Map<string, ReturnType<typeof setTimeout>>();

	constructor(id: string, connection: WebSocket, url: string | null) {
		this.id = id;
		this.connection = connection;
		this.url = url;
	}
}

export class MachineManager {
	machines = $state.raw(new Map<string, Machine>());
	selectedMachineId = $state<string | null>(null);
	selectedMachine = $derived(
		this.selectedMachineId ? (this.machines.get(this.selectedMachineId) ?? null) : null
	);
	private socket_urls = new Map<WebSocket, string>();
	private last_message_at = new WeakMap<WebSocket, number>();
	private ignored_closures = new WeakSet<WebSocket>();
	private reconnect_attempts = new Map<string, number>();
	private reconnect_timers = new Map<string, ReturnType<typeof setTimeout>>();
	private manually_disconnected = new Set<string>();
	private connection_watchdog_timer: ReturnType<typeof setInterval> | null = null;

	connect(url: string, options: { force?: boolean } = {}): void {
		this.manually_disconnected.delete(url);
		clearTimeout(this.reconnect_timers.get(url));
		this.reconnect_timers.delete(url);

		if (options.force) {
			this.closeSocketsForUrl(url);
		} else if (this.hasUsableSocketForUrl(url)) {
			return;
		}

		const ws = new WebSocket(url);
		this.socket_urls.set(ws, url);
		this.last_message_at.set(ws, Date.now());

		ws.onopen = () => {
			console.log(`[MachineManager] Connected to ${url}`);
			this.reconnect_attempts.set(url, 0);
		};

		ws.onmessage = (message) => {
			this.last_message_at.set(ws, Date.now());
			this.handleEvent(ws, JSON.parse(message.data) as SocketEvent);
		};

		ws.onerror = (error) => {
			console.error(`[MachineManager] WebSocket error:`, error);
		};

		ws.onclose = () => {
			console.log(`[MachineManager] WebSocket closed for ${url}`);
			this.socket_urls.delete(ws);
			const machine = this.machineFor(ws);
			if (machine) machine.status = 'disconnected';
			if (!this.ignored_closures.has(ws) && !this.manually_disconnected.has(url)) {
				this.scheduleReconnect(url);
			}
		};
	}

	ensureConnected(url: string): void {
		if (this.manually_disconnected.has(url) || this.hasUsableSocketForUrl(url)) return;
		this.connect(url);
	}

	private scheduleReconnect(url: string): void {
		if (this.hasUsableSocketForUrl(url) || this.reconnect_timers.has(url)) return;
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

	startConnectionWatchdog(options: { defaultUrl?: string } = {}): () => void {
		this.stopConnectionWatchdog();
		const defaultUrl = options.defaultUrl;

		const tick = () => {
			// A socket that has delivered nothing for STALE_MS (the server sends a
			// heartbeat every 2 s) is replaced now: closing a dead socket can take
			// the browser a minute to report.
			const now = Date.now();
			for (const [ws, url] of this.socket_urls) {
				if (ws.readyState !== WebSocket.CONNECTING && ws.readyState !== WebSocket.OPEN) continue;
				if (now - (this.last_message_at.get(ws) ?? now) < STALE_MS) continue;
				console.warn(`[MachineManager] Nothing from ${url} for ${STALE_MS} ms; reconnecting`);
				this.connect(url, { force: true });
			}
			// A pending reconnect timer owns the retry (and its backoff).
			if (defaultUrl && !this.reconnect_timers.has(defaultUrl)) {
				this.ensureConnected(defaultUrl);
			}
		};

		tick();
		this.connection_watchdog_timer = setInterval(tick, CONNECTION_WATCHDOG_INTERVAL_MS);
		return () => this.stopConnectionWatchdog();
	}

	stopConnectionWatchdog(): void {
		if (this.connection_watchdog_timer === null) return;
		clearInterval(this.connection_watchdog_timer);
		this.connection_watchdog_timer = null;
	}

	/** Whether the machine's websocket has delivered anything recently. */
	isLive(machine: Machine | null): boolean {
		if (!machine || machine.status !== 'connected') return false;
		if (machine.connection.readyState !== WebSocket.OPEN) return false;
		return Date.now() - (this.last_message_at.get(machine.connection) ?? 0) < STALE_MS;
	}

	disconnect(machineId: string): void {
		const machine = this.machines.get(machineId);
		if (!machine) return;
		this.clearRemovalTimers(machine);
		const url = this.socket_urls.get(machine.connection);
		if (url) {
			this.manually_disconnected.add(url);
			clearTimeout(this.reconnect_timers.get(url));
			this.reconnect_timers.delete(url);
		}
		machine.connection.close();
		const updated = new Map(this.machines);
		updated.delete(machineId);
		this.machines = updated;
		if (this.selectedMachineId === machineId) {
			this.selectedMachineId = updated.keys().next().value ?? null;
		}
	}

	selectMachine(machineId: string | null): void {
		this.selectedMachineId = machineId;
	}

	private hasUsableSocketForUrl(url: string): boolean {
		for (const [socket, socketUrl] of this.socket_urls) {
			if (socketUrl !== url) continue;
			if (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN) {
				return true;
			}
		}
		return false;
	}

	private closeSocketsForUrl(url: string): void {
		for (const [socket, socketUrl] of this.socket_urls) {
			if (socketUrl !== url) continue;
			if (socket.readyState === WebSocket.CLOSING || socket.readyState === WebSocket.CLOSED)
				continue;
			this.ignored_closures.add(socket);
			socket.close();
		}
	}

	private machineFor(ws: WebSocket): Machine | null {
		for (const machine of this.machines.values()) {
			if (machine.connection === ws) return machine;
		}
		return null;
	}

	private handleEvent(ws: WebSocket, event: SocketEvent): void {
		if (event.tag === 'identity') return this.handleIdentity(ws, event.data);
		const machine = this.machineFor(ws);
		if (!machine) {
			console.warn('[MachineManager] Received event before identity', event);
			return;
		}
		switch (event.tag) {
			case 'known_object':
				return this.handleKnownObject(machine, event.data);
			case 'camera_health':
				machine.cameraHealth = new Map(Object.entries(event.data.cameras));
				return;
			case 'runtime_stats':
				machine.runtimeStats = event.data.payload as Record<string, unknown>;
				return;
			case 'system_status':
				return this.handleSystemStatus(machine, event.data);
			case 'sorter_state':
				machine.sorterState = event.data;
				return;
			case 'cameras_config':
				machine.camerasConfig = event.data;
				return;
			case 'sorting_profile_status':
				machine.sortingProfileStatus = event.data;
		}
	}

	private handleIdentity(ws: WebSocket, identity: MachineIdentityData): void {
		const url = this.socket_urls.get(ws) ?? null;
		let machine = this.machines.get(identity.machine_id);
		if (!machine) {
			machine = new Machine(identity.machine_id, ws, url);
			this.machines = new Map(this.machines).set(identity.machine_id, machine);
		} else {
			if (machine.connection !== ws) machine.connection.close();
			machine.connection = ws;
			machine.url = url ?? machine.url;
			machine.status = 'connected';
		}
		machine.identity = identity;
		if (!this.selectedMachineId) this.selectedMachineId = identity.machine_id;
		console.log(`[MachineManager] Machine identified: ${identity.machine_id}`);
	}

	private handleKnownObject(machine: Machine, obj: KnownObjectData): void {
		// Every known_object event reduces into the shared piece store — the
		// records page and RecentObjects both view it. Runs before the ring's
		// early returns so dead pieces still reach the store (they exist as
		// durable records) even though the ring drops them.
		pieceStore.upsertFromWs(machine.id, obj);

		// Aborted (teardown) or dead (reaped by the backend after going silent
		// too long without distributing): the piece will never progress. Drop it
		// from the buffer immediately so it can't linger.
		if (obj.aborted || obj.dead) {
			this.clearRemovalTimer(machine, obj.uuid);
			if (machine.recentObjects.some((o) => o.uuid === obj.uuid)) {
				machine.recentObjects = machine.recentObjects.filter((o) => o.uuid !== obj.uuid);
			}
			return;
		}

		const existing_idx = machine.recentObjects.findIndex((o) => o.uuid === obj.uuid);
		const merged_obj = mergeKnownObject(machine.recentObjects[existing_idx], obj);
		if (!shouldKeepRecentObject(merged_obj)) {
			if (existing_idx >= 0) this.scheduleRemoval(machine, merged_obj.uuid);
			return;
		}
		this.clearRemovalTimer(machine, merged_obj.uuid);
		if (existing_idx >= 0) {
			const updated_objects = [...machine.recentObjects];
			updated_objects[existing_idx] = merged_obj;
			machine.recentObjects = updated_objects;
		} else {
			machine.recentObjects = [merged_obj, ...machine.recentObjects].slice(
				0,
				RECENT_OBJECT_BUFFER_LIMIT
			);
		}
	}

	private clearRemovalTimer(machine: Machine, uuid: string): void {
		clearTimeout(machine.removalTimers.get(uuid));
		machine.removalTimers.delete(uuid);
	}

	private clearRemovalTimers(machine: Machine): void {
		for (const timer of machine.removalTimers.values()) clearTimeout(timer);
		machine.removalTimers.clear();
	}

	private scheduleRemoval(machine: Machine, uuid: string): void {
		if (machine.removalTimers.has(uuid)) return;
		const timer = setTimeout(() => {
			machine.removalTimers.delete(uuid);
			const existing = machine.recentObjects.find((o) => o.uuid === uuid);
			if (!existing || shouldKeepRecentObject(existing)) return;
			machine.recentObjects = machine.recentObjects.filter((o) => o.uuid !== uuid);
		}, RECENT_OBJECT_REMOVAL_GRACE_MS);
		machine.removalTimers.set(uuid, timer);
	}

	private handleSystemStatus(machine: Machine, data: SystemStatusData): void {
		const shouldClearRecentObjects =
			data.hardware_state === 'homing' ||
			(data.hardware_state === 'standby' && machine.systemStatus?.hardware_state !== 'standby');
		if (shouldClearRecentObjects) {
			this.clearRemovalTimers(machine);
			pieceStore.clearWsEntries(machine.id);
			machine.recentObjects = [];
		}
		machine.systemStatus = data;
	}

	applySystemStatusToSelected(data: SystemStatusData): void {
		if (this.selectedMachine) this.handleSystemStatus(this.selectedMachine, data);
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
}
