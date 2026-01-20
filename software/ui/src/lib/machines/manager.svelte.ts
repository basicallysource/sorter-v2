import type { SocketEvent, CameraName, FrameData } from '$lib/api/events';
import type { MachineState, MachineIdentity } from './types';
import { isIdentityEvent, isFrameEvent, isHeartbeatEvent } from './types';

export class MachineManager {
	machines = $state(new Map<string, MachineState>());
	selectedMachineId = $state<string | null>(null);
	private pending_connections = new Map<WebSocket, string>();

	selectedMachine = $derived.by(() => {
		if (!this.selectedMachineId) return null;
		return this.machines.get(this.selectedMachineId) ?? null;
	});

	connect(url: string): void {
		const ws = new WebSocket(url);
		this.pending_connections.set(ws, url);

		ws.onopen = () => {
			console.log(`[MachineManager] Connected to ${url}`);
		};

		ws.onmessage = (message) => {
			const event = JSON.parse(message.data) as SocketEvent;
			this.handleEvent(ws, event);
		};

		ws.onerror = (error) => {
			console.error(`[MachineManager] WebSocket error:`, error);
		};

		ws.onclose = () => {
			console.log(`[MachineManager] WebSocket closed`);
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
		};
	}

	disconnect(machineId: string): void {
		const machine = this.machines.get(machineId);
		if (machine) {
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
			}
		}
	}

	private handleIdentity(ws: WebSocket, identity: MachineIdentity): void {
		this.pending_connections.delete(ws);

		const existing = this.machines.get(identity.machine_id);
		if (existing) {
			existing.connection.close();
		}

		const updated = new Map(this.machines);
		updated.set(identity.machine_id, {
			identity,
			connection: ws,
			status: 'connected',
			frames: new Map(),
			lastHeartbeat: null
		});
		this.machines = updated;

		if (!this.selectedMachineId) {
			this.selectedMachineId = identity.machine_id;
		}

		console.log(`[MachineManager] Machine identified: ${identity.machine_id}`);
	}

	private handleFrame(machineId: string, frame: FrameData): void {
		const machine = this.machines.get(machineId);
		if (!machine) return;

		const updated_frames = new Map(machine.frames);
		updated_frames.set(frame.camera, frame);

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
