// What the doors' set-up screens share: the machine's doors as it last said
// they are, the one action running now, and the sentence each action left
// where it was pressed. One action runs at a time, so nothing is pressed
// twice or over another; a refresh started before an action is dropped, so
// it never puts back what the action changed.
import { errorMessage } from '$lib/api/http';
import { getDoors, type DoorLayer, type Doors, type DoorsAnswer } from '$lib/api/doors';

export type DoorStatus = {
	label: string;
	tone: 'neutral' | 'success' | 'warning' | 'danger';
	// One line under the layer's name.
	line: string;
};

export type Note = { tone: 'success' | 'info' | 'warning'; title: string; text?: string };

export class DoorsController {
	doors = $state<Doors | null>(null);
	// Why the doors could not be read at all.
	loadError = $state<string | null>(null);
	// The action running now, by its key ("scan", "move-1-open").
	busy = $state<string | null>(null);
	// The layer whose door is being found by turning it by hand.
	matching = $state<number | null>(null);
	// Each place's failure, and what an action there said it did.
	errors = $state<Record<string, string>>({});
	notes = $state<Record<string, Note>>({});

	#base: () => string;
	#generation = 0;

	constructor(base: () => string) {
		this.#base = base;
	}

	get base(): string {
		return this.#base();
	}

	// A door moving on its own: the slow search for its stops.
	get searching(): boolean {
		return this.doors?.search?.state === 'running';
	}

	// Nothing else may move a door or start something now.
	get held(): boolean {
		return this.busy !== null || this.searching || this.matching !== null;
	}

	async refresh(): Promise<void> {
		if (this.busy) return;
		const generation = this.#generation;
		try {
			const doors = await getDoors(this.base);
			if (generation !== this.#generation || this.busy) return;
			this.doors = doors;
			this.loadError = null;
		} catch (e) {
			if (generation !== this.#generation) return;
			this.loadError = errorMessage(e, 'The machine did not answer.');
		}
	}

	// Runs one action. Its failure is kept for `place`, where it was pressed.
	// `note` turns its answer into a sentence worth keeping, kept for
	// `notePlace` (`place` when left out).
	async run(
		key: string,
		place: string,
		call: (base: string) => Promise<DoorsAnswer>,
		note?: (answer: DoorsAnswer) => Note | null,
		notePlace: string = place
	): Promise<DoorsAnswer | null> {
		if (this.busy) return null;
		this.busy = key;
		this.#generation++;
		this.clear(place);
		// What the last action said is old news once another starts.
		this.notes = {};
		let answer: DoorsAnswer | null = null;
		try {
			answer = await call(this.base);
			this.doors = answer.doors;
			const said = note?.(answer);
			if (said) this.notes = { ...this.notes, [notePlace]: said };
		} catch (e) {
			this.errors = { ...this.errors, [place]: errorMessage(e) };
		} finally {
			this.busy = null;
			this.#generation++;
		}
		// A failure may still have changed something (a servo was unplugged).
		if (!answer) void this.refresh();
		return answer;
	}

	fail(place: string, message: string): void {
		this.errors = { ...this.errors, [place]: message };
	}

	clear(place: string): void {
		if (place in this.errors) {
			const errors = { ...this.errors };
			delete errors[place];
			this.errors = errors;
		}
		if (place in this.notes) {
			const notes = { ...this.notes };
			delete notes[place];
			this.notes = notes;
		}
	}
}

export function layerName(index: number): string {
	return `Layer ${index + 1}`;
}

export function doorStatus(layer: DoorLayer): DoorStatus {
	if (layer.kind === 'fixed') {
		return { label: 'Always shut', tone: 'neutral', line: 'It has no servo.' };
	}
	if (layer.servo_id == null) {
		return { label: 'No servo yet', tone: 'neutral', line: 'Its servo is not found yet.' };
	}
	if (layer.available === false) {
		return {
			label: 'Not answering',
			tone: 'danger',
			line: layer.error ?? `Servo ${layer.servo_id} does not answer.`
		};
	}
	if (!layer.calibrated) {
		return {
			label: 'Not set up',
			tone: 'warning',
			line: `Servo ${layer.servo_id}. Where it stops is not found yet.`
		};
	}
	if (layer.error) return { label: 'Needs a look', tone: 'warning', line: layer.error };
	return { label: 'Set up', tone: 'success', line: `Servo ${layer.servo_id}` };
}
