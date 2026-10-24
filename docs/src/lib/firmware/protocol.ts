// The wire format the Pico interface firmware speaks over its USB serial port.
//
// Source of truth: software/firmware/sorter_interface_firmware/ (message.cpp,
// cobs.c, crc.c, and the command tables in sorter_interface_firmware.cpp), and
// the host side in software/sorter/backend/hardware/bus.py. A frame is
//
//   address, command, channel, payload length, payload..., CRC-32 (little endian)
//
// COBS-encoded, then closed with a 0x00 byte. All numbers in a payload are
// little endian. The high bit of the command byte in a reply means "error", and
// the payload is then a text message.
//
// This file is plain data and byte shuffling with no browser API in it, so it
// can be run and checked under Node.

export const COMMANDS = {
	INIT: 0x00,
	PING: 0x01,
	GET_OBSERVABILITY: 0x03,
	GET_VERSION: 0x04,
	STEPPER_MOVE_STEPS: 0x10,
	STEPPER_MOVE_AT_SPEED: 0x11,
	STEPPER_IS_STOPPED: 0x14,
	STEPPER_GET_POSITION: 0x15,
	STEPPER_SET_POSITION: 0x16,
	STEPPER_HOME: 0x17,
	STEPPER_DRV_SET_ENABLED: 0x20,
	STEPPER_DRV_SET_MICROSTEPS: 0x21,
	STEPPER_DRV_SET_CURRENT: 0x22,
	STEPPER_DRV_READ_REGISTER: 0x28,
	DIGITAL_READ: 0x30,
	DIGITAL_WRITE: 0x31,
	DIGITAL_WRITE_PWM: 0x32,
	SERVO_MOVE_TO: 0x40,
	SERVO_GET_POSITION: 0x43,
	SERVO_SET_ENABLED: 0x46
} as const;

export type CommandName = keyof typeof COMMANDS;

const NAMES = new Map<number, string>(Object.entries(COMMANDS).map(([name, code]) => [code, name]));

/** The command's name for the log, or its hex code if this page never sends it. */
export function commandName(code: number): string {
	return NAMES.get(code & 0x7f) ?? `0x${(code & 0x7f).toString(16).padStart(2, '0')}`;
}

// Largest payload the firmware accepts: a COBS frame is at most 254 bytes, minus
// the 4-byte header and the 4-byte CRC.
export const MAX_PAYLOAD = 246;

let crcTable: Uint32Array | undefined;

/** CRC-32 as zlib computes it (reflected, polynomial 0xEDB88320, inverted in and out). */
export function crc32(data: Uint8Array): number {
	if (!crcTable) {
		crcTable = new Uint32Array(256);
		for (let n = 0; n < 256; n++) {
			let c = n;
			for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
			crcTable[n] = c >>> 0;
		}
	}
	let crc = 0xffffffff;
	for (const byte of data) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
	return (crc ^ 0xffffffff) >>> 0;
}

/** COBS as the firmware does it (cobs.c): no 0 in the output, a count byte in front. */
export function cobsEncode(message: Uint8Array): Uint8Array {
	const out: number[] = [1];
	let counter = 0;
	for (const byte of message) {
		if (byte === 0) counter = out.length;
		out.push(byte);
		out[counter]++;
	}
	return Uint8Array.from(out);
}

/** Inverse of {@link cobsEncode}. Throws on a framing error. */
export function cobsDecode(encoded: Uint8Array): Uint8Array {
	if (encoded.length === 0) throw new Error('empty frame');
	const out: number[] = [];
	let counter = encoded[0];
	for (let i = 1; i < encoded.length; i++) {
		const byte = encoded[i];
		if (byte === 0) throw new Error('zero inside a frame');
		if (counter === 1) {
			out.push(0);
			counter = byte;
		} else {
			out.push(byte);
			counter--;
		}
	}
	if (counter > 1) throw new Error('frame cut short');
	return Uint8Array.from(out);
}

/** Everything that goes on the wire for one command, including the closing 0x00. */
export function encodeRequest(
	address: number,
	command: number,
	channel: number,
	payload: Uint8Array = new Uint8Array()
): Uint8Array {
	if (payload.length > MAX_PAYLOAD) throw new Error(`payload is ${payload.length} bytes, the most is ${MAX_PAYLOAD}`);
	const body = new Uint8Array(4 + payload.length + 4);
	body.set([address, command, channel, payload.length]);
	body.set(payload, 4);
	new DataView(body.buffer).setUint32(4 + payload.length, crc32(body.subarray(0, 4 + payload.length)), true);
	const encoded = cobsEncode(body);
	const wire = new Uint8Array(encoded.length + 1);
	wire.set(encoded);
	return wire;
}

export type Response = {
	address: number;
	command: number;
	channel: number;
	payload: Uint8Array;
	/** The firmware answered with its error bit set; `payload` is then its message. */
	error: boolean;
};

/** Decode one frame (without its closing 0x00). Throws if it is garbled or its CRC is wrong. */
export function decodeResponse(frame: Uint8Array): Response {
	const body = cobsDecode(frame);
	if (body.length < 8) throw new Error('reply too short');
	const view = new DataView(body.buffer, body.byteOffset, body.byteLength);
	const crcAt = body.length - 4;
	if (crc32(body.subarray(0, crcAt)) !== view.getUint32(crcAt, true)) throw new Error('CRC mismatch');
	const length = body[3];
	return {
		address: body[0],
		command: body[1] & 0x7f,
		channel: body[2],
		payload: body.slice(4, Math.min(4 + length, crcAt)),
		error: (body[1] & 0x80) !== 0
	};
}

// Payload builders. Each mirrors the struct format in the firmware's command table.

export const u8 = (...values: number[]) => Uint8Array.from(values);

export function pack(format: string, ...values: number[]): Uint8Array {
	const sizes: Record<string, number> = { B: 1, H: 2, I: 4, i: 4 };
	const out = new Uint8Array([...format].reduce((n, f) => n + sizes[f], 0));
	const view = new DataView(out.buffer);
	let at = 0;
	[...format].forEach((f, k) => {
		const v = values[k];
		if (f === 'B') view.setUint8(at, v);
		else if (f === 'H') view.setUint16(at, v, true);
		else if (f === 'I') view.setUint32(at, v, true);
		else view.setInt32(at, v, true);
		at += sizes[f];
	});
	return out;
}

export const asText = (payload: Uint8Array) => new TextDecoder().decode(payload);
export const asJson = (payload: Uint8Array) => JSON.parse(asText(payload));
export const asInt32 = (payload: Uint8Array) => new DataView(payload.buffer, payload.byteOffset, 4).getInt32(0, true);
export const asUint16 = (payload: Uint8Array) => new DataView(payload.buffer, payload.byteOffset, 2).getUint16(0, true);
export const asUint32 = (payload: Uint8Array) => new DataView(payload.buffer, payload.byteOffset, 4).getUint32(0, true);

export const hex = (bytes: Uint8Array) => Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join(' ');
