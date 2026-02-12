import type {
	SocketEvent,
	CameraName,
	FrameData,
	KnownObjectData,
	DistributionLayoutData
} from '$lib/api/events';
import type { MachineState, MachineIdentity } from './types';
import {
	isIdentityEvent,
	isFrameEvent,
	isHeartbeatEvent,
	isKnownObjectEvent,
	isDistributionLayoutEvent
} from './types';

const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 30000;

export class MachineManager {
	machines = $state(new Map<string, MachineState>());
	selectedMachineId = $state<string | null>(null);
	private pending_connections = new Map<WebSocket, string>();
	private reconnect_attempts = new Map<string, number>();
	private reconnect_timers = new Map<string, ReturnType<typeof setTimeout>>();
	private manually_disconnected = new Set<string>();

	selectedMachine = $derived.by(() => {
		if (!this.selectedMachineId) return null;
		return this.machines.get(this.selectedMachineId) ?? null;
	});

	connect(url: string): void {
		this.manually_disconnected.delete(url);

		const existing_timer = this.reconnect_timers.get(url);
		if (existing_timer) {
			clearTimeout(existing_timer);
			this.reconnect_timers.delete(url);
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
			if (!this.manually_disconnected.has(reconnect_url)) {
				this.scheduleReconnect(reconnect_url);
			}
		};
	}

	private scheduleReconnect(url: string): void {
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

	disconnect(machineId: string): void {
		const machine = this.machines.get(machineId);
		if (machine) {
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

	private handleEvent(ws: WebSocket, event: SocketEvent): void {
		if (isIdentityEvent(event)) {
			this.handleIdentity(ws, event.data);
		} else {
			const machineId = this.findMachineIdBySocket(ws);
			if (!machineId) {
				console.warn('[MachineManager] Received event before identity', event);
				return;
			}

			if (isFrameEvent(event)) {
				this.handleFrame(machineId, event.data);
			} else if (isHeartbeatEvent(event)) {
				this.handleHeartbeat(machineId, event.data.timestamp);
			} else if (isKnownObjectEvent(event)) {
				this.handleKnownObject(machineId, event.data);
			} else if (isDistributionLayoutEvent(event)) {
				this.handleLayout(machineId, event.data);
			}
		}
	}

	private handleIdentity(ws: WebSocket, identity: MachineIdentity): void {
		const url = this.pending_connections.get(ws);
		this.pending_connections.delete(ws);

		const existing = this.machines.get(identity.machine_id);
		if (existing && existing.connection !== ws) {
			existing.connection.close();
		}

		const updated = new Map(this.machines);
		updated.set(identity.machine_id, {
			identity,
			connection: ws,
			status: 'connected',
			frames: existing?.frames ?? new Map(),
			lastHeartbeat: null,
			recentObjects: existing?.recentObjects ?? [],
			layout: existing?.layout ?? null
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

	private handleFrame(machineId: string, frame: FrameData): void {
		const machine = this.machines.get(machineId);
		if (!machine) return;

		const updated_frames = new Map();
		updated_frames.set(frame.camera, frame);
		
		for (const [camera, existingFrame] of machine.frames) {
			if (camera !== frame.camera) {
				updated_frames.set(camera, existingFrame);
			}
		}

		const updated = new Map(this.machines);
		updated.set(machineId, { ...machine, frames: updated_frames });
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

		const existing_idx = machine.recentObjects.findIndex((o) => o.uuid === obj.uuid);
		let updated_objects: KnownObjectData[];

		if (existing_idx >= 0) {
			updated_objects = [...machine.recentObjects];
			updated_objects[existing_idx] = obj;
		} else {
			updated_objects = [obj, ...machine.recentObjects].slice(0, 10);
		}

		const updated = new Map(this.machines);
		updated.set(machineId, { ...machine, recentObjects: updated_objects });
		this.machines = updated;
	}

	private handleLayout(machineId: string, layout: DistributionLayoutData): void {
		const machine = this.machines.get(machineId);
		if (!machine) return;

		const updated = new Map(this.machines);
		updated.set(machineId, { ...machine, layout });
		this.machines = updated;
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
