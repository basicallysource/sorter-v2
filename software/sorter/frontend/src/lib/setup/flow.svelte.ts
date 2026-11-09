// The setup flow's shared state: the machine's setup summary, the hardware's
// live state, and the marks only the person knows (wizard-storage.ts). Each
// step component takes the flow, does its own loading, saving and errors, and
// calls `reload()` when it changed something the summary reports.

import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
import { DEFAULT_HIVE_URL } from '$lib/hive/link-flow';
import { errorMessage } from '$lib/api/http';
import {
	getHiveTargets,
	getSetupSummary,
	officialHive,
	type HardwareState,
	type HiveTarget,
	type SetupSummary
} from '$lib/api/setup';
import { startHardware } from '$lib/api/system';
import { getSharing } from '$lib/sharing/api';
import type { MachineContext } from '$lib/machines/types';
import type { StepContext } from './steps';
import { loadMarks, saveMarks, type SetupMarks } from './wizard-storage';

export class SetupFlow {
	summary = $state.raw<SetupSummary | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);
	marks = $state<SetupMarks>({});
	// The person agreed to what the sorter shares; null until known.
	sharingAgreed = $state<boolean | null>(null);
	hive = $state.raw<HiveTarget | null>(null);
	// Starting the hardware from a step.
	starting = $state(false);
	startError = $state<string | null>(null);
	// What Continue saves first, set by the step that is open (the name).
	beforeNext: (() => Promise<boolean>) | null = null;

	#machine: MachineContext;
	#marksFor = '';
	#seq = 0;

	constructor(machine: MachineContext) {
		this.#machine = machine;
	}

	get base(): string {
		return machineHttpBaseUrlFromWsUrl(this.#machine.machine?.url) ?? getBackendHttpBase();
	}

	get machineId(): string {
		return this.#machine.machine?.identity?.machine_id ?? this.summary?.machine.machine_id ?? '';
	}

	// The hardware's state as the machine reports it live, or as the last summary had it.
	get hardwareState(): HardwareState {
		return this.#machine.machine?.systemStatus?.hardware_state ?? this.summary?.hardware.state ?? 'standby';
	}

	get hardwareError(): string | null {
		const live = this.#machine.machine?.systemStatus;
		const error = live ? live.hardware_error : this.summary?.hardware.error;
		return error ? [error.title, error.message].filter(Boolean).join(': ') : null;
	}

	get homingStep(): string | null {
		return this.#machine.machine?.systemStatus?.homing_step ?? this.summary?.hardware.homing_step ?? null;
	}

	// What the steps judge themselves by; null until the summary has loaded.
	get context(): StepContext | null {
		if (!this.summary) return null;
		return {
			summary: this.summary,
			marks: this.marks,
			sharingAgreed: this.sharingAgreed,
			hiveConnected: this.hive !== null
		};
	}

	// The motors are powered and the boards open.
	get hardwareUp(): boolean {
		return this.hardwareState === 'initialized' || this.hardwareState === 'ready';
	}

	get hardwareBusy(): boolean {
		return this.starting || this.hardwareState === 'initializing' || this.hardwareState === 'homing';
	}

	async reload(): Promise<void> {
		const seq = ++this.#seq;
		const base = this.base;
		this.loading = true;
		try {
			const [summary, sharing, hive] = await Promise.all([
				getSetupSummary(base),
				getSharing(base).catch(() => null),
				getHiveTargets(base).catch(() => null)
			]);
			if (seq !== this.#seq) return;
			this.summary = summary;
			this.error = null;
			if (sharing) {
				this.sharingAgreed = !sharing.consent.needs_consent && !sharing.consent.needs_review;
			}
			if (hive) this.hive = officialHive(hive, DEFAULT_HIVE_URL);
			this.#loadMarks();
		} catch (e) {
			if (seq === this.#seq) this.error = errorMessage(e, 'The setup summary did not load.');
		} finally {
			if (seq === this.#seq) this.loading = false;
		}
	}

	#loadMarks() {
		const id = this.machineId;
		if (!id || id === this.#marksFor) return;
		this.#marksFor = id;
		this.marks = loadMarks(id);
	}

	mark(changes: Partial<SetupMarks>) {
		this.marks = { ...this.marks, ...changes };
		if (this.#marksFor) saveMarks(this.#marksFor, this.marks);
	}

	// Powers the motors and opens the boards, without homing. The progress and
	// any fault come through the machine's live status.
	async startHardware(): Promise<void> {
		this.starting = true;
		this.startError = null;
		try {
			await startHardware(this.base);
		} catch (e) {
			this.startError = errorMessage(e, 'The motors did not power on.');
		} finally {
			this.starting = false;
		}
	}
}
