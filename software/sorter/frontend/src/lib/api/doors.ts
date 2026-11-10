// The layer doors' serial servos (backend server/routers/doors.py): which servo
// turns which door, and the two positions each door turns between. Every call
// throws an ApiError carrying the server's own sentence when it fails.
import { getJson, postJson } from './http';

export type DoorEnd = 'closed' | 'open';

// One layer's door, the top layer first (index 0 is layer 1).
export type DoorLayer = {
	layer_index: number;
	// `fixed`: the slip ring chute's bottom door, which has no servo and is always shut.
	kind: 'servo' | 'fixed';
	servo_id: number | null;
	calibrated: boolean;
	// In the servo's own counts.
	closed_position: number | null;
	open_position: number | null;
	// Read from the running hardware; null when it is not started.
	available: boolean | null;
	error: string | null;
	is_open: boolean | null;
	position: number | null;
	model: string | null;
	volts?: number | null;
	temperature_c?: number | null;
};

// A servo the last scan heard. `shared`: two or more servos answer to this
// number at once. `unknown`: a model the machine does not know.
export type FoundServo = {
	servo_id: number;
	state: 'ok' | 'shared' | 'unknown';
	model: string | null;
	position: number | null;
	volts: number | null;
	temperature_c: number | null;
	// Still on the number every new servo comes with.
	factory_id: boolean;
	// The layer whose door it turns, if any.
	layer_index: number | null;
};

export type DoorSearch = {
	layer_index: number;
	servo_id: number;
	state: 'running' | 'asking' | 'done' | 'failed';
	message: string;
	travel_degrees?: number;
	// An end where the door met nothing before the servo's own limit.
	open_ended?: string[];
};

export type Doors = {
	// `bus` when the doors are serial servos on the control board's own bus.
	backend: string | null;
	ready: boolean;
	reason: string | null;
	layer_count: number;
	fixed_layer: number | null;
	layers: DoorLayer[];
	servos: FoundServo[];
	shared_ids: number[];
	// Whether the servos have been scanned since the backend started; before
	// that, an empty `servos` says nothing.
	scanned: boolean;
	watching: boolean;
	search: DoorSearch | null;
	// For every servo that has ever answered: how often it was asked, how often it
	// had to be asked again, and how often it never answered.
	bus: { servo_id: number; asked: number; repeated: number; unanswered: number }[];
};

export type DoorsAnswer = { ok: true; message: string | null; doors: Doors };

export type HandWatch = {
	ok: true;
	// Degrees each servo has turned since the watch started, by servo number.
	turned_degrees: Record<string, number>;
	// The one servo that was turned by hand, once exactly one has.
	moved: number | null;
};

const layer = (index: number, action: string) => `/api/doors/layers/${index}/${action}`;

export const getDoors = (base: string) => getJson<Doors>(base, '/api/doors');

export const scanServos = (base: string) => postJson<DoorsAnswer>(base, '/api/doors/scan');

export const renumberServo = (base: string, servoId: number, newId: number) =>
	postJson<DoorsAnswer>(base, `/api/doors/servos/${servoId}/id`, { new_id: newId });

export const startHandWatch = (base: string) =>
	postJson<DoorsAnswer>(base, '/api/doors/watch/start');

export const readHandWatch = (base: string) => getJson<HandWatch>(base, '/api/doors/watch');

export const stopHandWatch = (base: string) => postJson<DoorsAnswer>(base, '/api/doors/watch/stop');

// null takes the servo away from the layer.
export const setLayerServo = (base: string, layerIndex: number, servoId: number | null) =>
	postJson<DoorsAnswer>(base, layer(layerIndex, 'servo'), { servo_id: servoId });

export const findStops = (base: string, layerIndex: number) =>
	postJson<DoorsAnswer>(base, layer(layerIndex, 'find-stops'));

export const stopFindingStops = (base: string) =>
	postJson<DoorsAnswer>(base, '/api/doors/find-stops/stop');

export const answerWhichEnd = (base: string, layerIndex: number, closedNow: boolean) =>
	postJson<DoorsAnswer>(base, layer(layerIndex, 'answer'), { closed_now: closedNow });

export const markDoorEnd = (base: string, layerIndex: number, end: DoorEnd) =>
	postJson<DoorsAnswer>(base, layer(layerIndex, 'mark'), { end });

export const nudgeDoorEnd = (base: string, layerIndex: number, end: DoorEnd, degrees: number) =>
	postJson<DoorsAnswer>(base, layer(layerIndex, 'nudge'), { end, degrees });

export const moveDoor = (base: string, layerIndex: number, to: DoorEnd) =>
	postJson<DoorsAnswer>(base, layer(layerIndex, 'move'), { to });

export const releaseDoors = (base: string) => postJson<DoorsAnswer>(base, '/api/doors/release');
