// A Web Serial connection to a control board running the interface firmware.
//
// Web Serial only exists in Chromium browsers, and TypeScript's DOM library
// does not describe it, so the few pieces used here are declared locally.

import {
	COMMANDS,
	asJson,
	asText,
	commandName,
	decodeResponse,
	encodeRequest,
	hex,
	type Response
} from './protocol';

type SerialPortLike = {
	open(options: { baudRate: number }): Promise<void>;
	close(): Promise<void>;
	readable: ReadableStream<Uint8Array> | null;
	writable: WritableStream<Uint8Array> | null;
};

type SerialLike = EventTarget & {
	requestPort(options?: {
		filters?: { usbVendorId: number; usbProductId?: number }[];
	}): Promise<SerialPortLike>;
};

// The Pico SDK's USB serial device, the same vendor and product id the machine's
// backend looks for (hardware/bus.py). A board that has never been flashed shows
// up as a USB drive instead, so it will not be in this list.
const PICO_CDC = { usbVendorId: 0x2e8a, usbProductId: 0x000a };

export const webSerialSupported = () => typeof navigator !== 'undefined' && 'serial' in navigator;

export class FirmwareError extends Error {}

export type LogEntry = {
	t: number;
	dir: 'tx' | 'rx' | 'info' | 'error';
	text: string;
};

export type LinkEvents = {
	onLog?: (entry: LogEntry) => void;
	/** The port went away: unplugged, or closed by the other end. */
	onClose?: () => void;
};

export class FirmwareLink {
	address = 0;

	private port: SerialPortLike | undefined;
	private writer: WritableStreamDefaultWriter<Uint8Array> | undefined;
	private reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
	private frame: number[] = [];
	private waiting: ((frame: Uint8Array) => void) | undefined;
	private chain: Promise<unknown> = Promise.resolve();
	private closing = false;

	constructor(private events: LinkEvents = {}) {}

	get connected() {
		return this.port !== undefined;
	}

	private log(dir: LogEntry['dir'], text: string) {
		this.events.onLog?.({ t: Date.now(), dir, text });
	}

	/** Ask the browser for a port. Must be called from a click. */
	async connect(showAllPorts = false) {
		const serial = (navigator as Navigator & { serial: SerialLike }).serial;
		const port = await serial.requestPort(showAllPorts ? {} : { filters: [PICO_CDC] });
		// The baud rate means nothing on a USB serial device, but the call needs one.
		await port.open({ baudRate: 115200 });
		if (!port.readable || !port.writable) {
			await port.close();
			throw new FirmwareError('The port opened without a data stream.');
		}
		this.port = port;
		this.closing = false;
		this.frame = [];
		this.writer = port.writable.getWriter();
		this.reader = port.readable.getReader();
		this.log('info', 'Port open.');
		void this.readLoop();
	}

	async disconnect() {
		this.closing = true;
		const { port, reader, writer } = this;
		this.port = undefined;
		this.waiting = undefined;
		try {
			await reader?.cancel();
		} catch {
			/* already gone */
		}
		try {
			reader?.releaseLock();
			writer?.releaseLock();
			await port?.close();
		} catch {
			/* already gone */
		}
		this.reader = this.writer = undefined;
		this.log('info', 'Port closed.');
	}

	private async readLoop() {
		const reader = this.reader;
		try {
			while (reader) {
				const { value, done } = await reader.read();
				if (done) break;
				for (const byte of value ?? []) this.feed(byte);
			}
		} catch {
			/* a read error is an unplug; handled below */
		}
		if (!this.closing && this.port) {
			this.port = undefined;
			this.reader = this.writer = undefined;
			this.log('error', 'The board disconnected.');
			this.events.onClose?.();
		}
	}

	private feed(byte: number) {
		if (byte !== 0) {
			// A frame is at most 254 bytes; anything longer is noise.
			if (this.frame.length < 300) this.frame.push(byte);
			return;
		}
		const frame = Uint8Array.from(this.frame);
		this.frame = [];
		if (frame.length === 0) return;
		if (this.waiting) this.waiting(frame);
		else this.log('error', `Unexpected data from the board: ${hex(frame)}`);
	}

	/**
	 * Send one command and wait for the matching reply. Calls are queued, so two
	 * buttons clicked together never put half-frames on the wire together.
	 * Rejects with a FirmwareError if the board reports an error or does not answer.
	 * A `quiet` request is left out of the log unless it fails, for polling.
	 */
	request(
		command: number,
		channel = 0,
		payload: Uint8Array = new Uint8Array(),
		timeoutMs = 1000,
		quiet = false
	): Promise<Response> {
		const run = () => this.exchange(command, channel, payload, timeoutMs, quiet);
		const result = this.chain.then(run, run);
		this.chain = result.catch(() => undefined);
		return result;
	}

	private async exchange(
		command: number,
		channel: number,
		payload: Uint8Array,
		timeoutMs: number,
		quiet: boolean
	) {
		if (!this.writer) throw new FirmwareError('Not connected.');
		const name = commandName(command);
		const wire = encodeRequest(this.address, command, channel, payload);
		if (!quiet) this.log('tx', `${name} ch${channel}${payload.length ? ` [${hex(payload)}]` : ''}`);

		const reply = new Promise<Uint8Array>((resolve, reject) => {
			const timer = setTimeout(() => {
				this.waiting = undefined;
				reject(new FirmwareError(`${name}: no answer from the board in ${timeoutMs} ms.`));
			}, timeoutMs);
			this.waiting = (frame) => {
				clearTimeout(timer);
				this.waiting = undefined;
				resolve(frame);
			};
		});
		// A reply that arrives after we stopped waiting must not be mistaken for the next one.
		this.frame = [];
		try {
			await this.writer.write(wire);
		} catch (e) {
			this.waiting = undefined;
			throw new FirmwareError(`${name}: could not write to the port (${(e as Error).message}).`);
		}

		let response: Response;
		try {
			response = decodeResponse(await reply);
		} catch (e) {
			if (e instanceof FirmwareError) {
				this.log('error', e.message);
				throw e;
			}
			const message = `${name}: garbled reply (${(e as Error).message}).`;
			this.log('error', message);
			throw new FirmwareError(message);
		}
		if (response.error) {
			const message = `${name}: ${asText(response.payload)}`;
			this.log('error', message);
			throw new FirmwareError(message);
		}
		if (response.command !== (command & 0x7f)) {
			const message = `${name}: the board answered a different command (${commandName(response.command)}).`;
			this.log('error', message);
			throw new FirmwareError(message);
		}
		if (!quiet) this.log('rx', response.payload.length ? hex(response.payload) : 'ok');
		return response;
	}

	/** Reset the board's hardware to its start state and learn what it has. */
	async identify() {
		// INIT talks to every stepper driver over UART, so it gets longer than a ping.
		const config = asJson((await this.request(COMMANDS.INIT, 0, undefined, 3000)).payload) as BoardConfig;
		// Older firmware lacks these two; the rest of the page still works without them.
		let version: BoardVersion | undefined;
		let observability: Observability = {};
		try {
			version = asJson((await this.request(COMMANDS.GET_VERSION)).payload);
		} catch {
			/* not fatal */
		}
		try {
			observability = asJson((await this.request(COMMANDS.GET_OBSERVABILITY)).payload);
		} catch {
			/* not fatal */
		}
		return { config, version, observability };
	}
}

export type BoardConfig = {
	device_name: string;
	hw?: string;
	stepper_count: number;
	stepper_names?: string[];
	digital_input_count: number;
	digital_output_count: number;
	servo_count: number;
};

export type BoardVersion = {
	firmware_version: string;
	variant: string;
	commit: string;
	build_time_utc: string;
};

export type Observability = {
	hw?: string;
	diag_pins?: number[];
	led_gpios?: number[];
};
