<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		FirmwareLink,
		webSerialSupported,
		type BoardConfig,
		type BoardVersion,
		type LogEntry,
		type Observability
	} from '$lib/firmware/link';
	import { COMMANDS, asInt32, asUint16, asUint32, hex, pack, u8 } from '$lib/firmware/protocol';

	// A bench tester for a control board running the interface firmware
	// (software/firmware/sorter_interface_firmware). It talks to the Pico over
	// Web Serial from the reader's own browser; nothing goes through a server.
	// The wire format is in $lib/firmware/protocol.ts.

	type StepperUi = {
		name: string;
		irun: number;
		ihold: number;
		microsteps: number;
		steps: number;
		speed: number;
		position: number | null;
		moving: boolean;
		applied: boolean;
		homeInput: number;
		homeLevel: 0 | 1;
		homeSpeed: number;
		driver: string[] | null;
	};

	const MICROSTEP_CHOICES = [1, 2, 4, 8, 16, 32, 64, 128, 256];
	const HOLD_DELAY = 8;
	const SERVO_CHANNELS = 16;

	// GPIO numbers behind each channel, from the firmware's hwcfg_*.h files, so a
	// reader chasing a wiring fault can see which Pico pin an input is.
	const PINS: Record<string, { inputs: number[]; outputs: number[] }> = {
		basically_v1_1: { inputs: [9, 8, 13, 12], outputs: [14, 15] },
		basically_v1_2: { inputs: [3, 2], outputs: [1, 6] },
		skr_pico: { inputs: [4, 3, 25, 16], outputs: [21, 23, 17, 18, 20] }
	};

	// TMC2209 DRV_STATUS bits that mean something is wrong with the motor or driver.
	const DRV_FLAGS: [number, string][] = [
		[0, 'over-temperature warning'],
		[1, 'over-temperature shutdown'],
		[2, 'short to ground on coil A'],
		[3, 'short to ground on coil B'],
		[4, 'short to supply on coil A'],
		[5, 'short to supply on coil B'],
		[6, 'open load on coil A (check the motor cable)'],
		[7, 'open load on coil B (check the motor cable)']
	];

	const supported = webSerialSupported();
	let stopping = 0; // bumped to cancel every polling loop at once
	let status = $state<'idle' | 'connecting' | 'ready'>('idle');
	let notice = $state<{ tone: 'error' | 'info'; text: string } | null>(null);
	let address = $state(0);
	let showAllPorts = $state(false);

	let config = $state<BoardConfig | null>(null);
	let version = $state<BoardVersion | null>(null);
	let observability = $state<Observability>({});

	let steppers = $state<StepperUi[]>([]);
	let servoChannel = $state(0);
	let servoAngle = $state(90);
	let servoEnabled = $state<boolean[]>(Array(SERVO_CHANNELS).fill(false));
	let servoReadout = $state<number | null>(null);
	let inputs = $state<(boolean | null)[]>([]);
	let live = $state(false);
	let outputs = $state<{ on: boolean; duty: number }[]>([]);

	let log = $state<LogEntry[]>([]);
	let logEl: HTMLElement | undefined = $state();

	const link = new FirmwareLink({
		onLog(entry) {
			log = [...log.slice(-299), entry];
		},
		onClose() {
			status = 'idle';
			live = false;
			notice = { tone: 'error', text: 'The board disconnected. Plug it back in and connect again.' };
		}
	});

	const hw = $derived(observability.hw ?? config?.hw ?? '');
	const pins = $derived(PINS[hw]);

	$effect(() => {
		log; // follow the newest line
		if (logEl) logEl.scrollTop = logEl.scrollHeight;
	});

	onDestroy(() => {
		stopping++;
		if (link.connected) void link.disconnect();
	});

	const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
	const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Math.round(Number(n) || 0)));
	const pretty = (name: string) => name.replace(/_/g, ' ');

	function message(e: unknown) {
		return e instanceof Error ? e.message : String(e);
	}

	/** Run a button's work; a failure becomes the red notice instead of a lost promise. */
	async function act(work: () => Promise<void>) {
		try {
			await work();
			if (notice?.tone === 'error') notice = null;
		} catch (e) {
			notice = { tone: 'error', text: message(e) };
		}
	}

	async function connect() {
		notice = null;
		status = 'connecting';
		link.address = clamp(address, 0, 255);
		address = link.address;
		try {
			await link.connect(showAllPorts);
		} catch (e) {
			status = 'idle';
			// Closing the picker without choosing a port is not an error.
			if ((e as Error).name !== 'NotFoundError') {
				notice = {
					tone: 'error',
					text: `${message(e)} If the port is busy, stop SorterOS or any other program using the board and try again.`
				};
			}
			return;
		}
		try {
			await identify();
			status = 'ready';
		} catch (e) {
			notice = {
				tone: 'error',
				text: `The port opened but the board did not answer as expected (${message(e)}). Check that it is running the interface firmware and that the address matches.`
			};
			await link.disconnect();
			status = 'idle';
		}
	}

	async function identify() {
		const info = await link.identify();
		config = info.config;
		version = info.version ?? null;
		observability = info.observability;
		const n = config.stepper_count;
		steppers = Array.from({ length: n }, (_, i) => ({
			name: config?.stepper_names?.[i] ?? `Stepper ${i}`,
			irun: 8,
			ihold: 2,
			microsteps: 8,
			steps: 800,
			speed: 400,
			position: null,
			moving: false,
			applied: false,
			homeInput: 0,
			homeLevel: 0,
			homeSpeed: -400,
			driver: null
		}));
		servoChannel = 0;
		servoEnabled = Array(SERVO_CHANNELS).fill(false);
		servoReadout = null;
		inputs = Array(config.digital_input_count).fill(null);
		outputs = Array.from({ length: config.digital_output_count }, () => ({ on: false, duty: 0 }));
		live = false;
	}

	async function disconnect() {
		live = false;
		stopping++;
		await link.disconnect();
		status = 'idle';
	}

	// ── Steppers ────────────────────────────────────────────────────────────

	const watching: number[] = [];

	async function applyDriver(i: number) {
		const s = steppers[i];
		await link.request(COMMANDS.STEPPER_DRV_SET_MICROSTEPS, i, pack('H', s.microsteps));
		await link.request(
			COMMANDS.STEPPER_DRV_SET_CURRENT,
			i,
			u8(clamp(s.irun, 0, 31), clamp(s.ihold, 0, 31), HOLD_DELAY)
		);
		await link.request(COMMANDS.STEPPER_DRV_SET_ENABLED, i, u8(1));
		s.applied = true;
	}

	/** Board start-up leaves every motor with zero current, so the first move sets it. */
	async function ready(i: number) {
		if (!steppers[i].applied) await applyDriver(i);
	}

	async function refresh(i: number) {
		const stopped = (await link.request(COMMANDS.STEPPER_IS_STOPPED, i, undefined, 1000, true)).payload[0] === 1;
		steppers[i].position = asInt32(
			(await link.request(COMMANDS.STEPPER_GET_POSITION, i, undefined, 1000, true)).payload
		);
		steppers[i].moving = !stopped;
	}

	/** Follow a motor while it moves, so the position and the moving flag stay current. */
	async function watch(i: number) {
		const token = (watching[i] = (watching[i] ?? 0) + 1);
		const epoch = stopping;
		for (let n = 0; n < 2400 && link.connected && watching[i] === token && epoch === stopping; n++) {
			await sleep(250);
			try {
				await refresh(i);
			} catch {
				return;
			}
			if (!steppers[i].moving) return;
		}
	}

	function changed(i: number) {
		steppers[i].applied = false;
	}

	const moveSteps = (i: number, dir: 1 | -1) =>
		act(async () => {
			await ready(i);
			const steps = clamp(steppers[i].steps, 1, 1_000_000);
			const accepted = (await link.request(COMMANDS.STEPPER_MOVE_STEPS, i, pack('i', dir * steps))).payload[0];
			if (!accepted) throw new Error('That motor is still moving. Press Stop and try again.');
			steppers[i].moving = true;
			void watch(i);
		});

	const runAtSpeed = (i: number, dir: 1 | -1) =>
		act(async () => {
			await ready(i);
			const speed = clamp(steppers[i].speed, 1, 4000);
			await link.request(COMMANDS.STEPPER_MOVE_AT_SPEED, i, pack('i', dir * speed));
			steppers[i].moving = true;
			void watch(i);
		});

	const stopStepper = (i: number) =>
		act(async () => {
			await link.request(COMMANDS.STEPPER_MOVE_AT_SPEED, i, pack('i', 0));
			void watch(i);
		});

	const stopAll = () =>
		act(async () => {
			for (let i = 0; i < steppers.length; i++) await link.request(COMMANDS.STEPPER_MOVE_AT_SPEED, i, pack('i', 0));
			for (let i = 0; i < steppers.length; i++) void watch(i);
		});

	const cutCurrent = (i: number) =>
		act(async () => {
			await link.request(COMMANDS.STEPPER_MOVE_AT_SPEED, i, pack('i', 0));
			await link.request(COMMANDS.STEPPER_DRV_SET_ENABLED, i, u8(0));
			steppers[i].applied = false;
			await refresh(i);
		});

	const zeroPosition = (i: number) =>
		act(async () => {
			await link.request(COMMANDS.STEPPER_SET_POSITION, i, pack('i', 0));
			await refresh(i);
		});

	const homeStepper = (i: number) =>
		act(async () => {
			await ready(i);
			const s = steppers[i];
			const speed = clamp(s.homeSpeed, -4000, 4000);
			if (speed === 0) throw new Error('Homing needs a speed other than 0. A negative speed turns the other way.');
			await link.request(COMMANDS.STEPPER_HOME, i, pack('iBB', speed, clamp(s.homeInput, 0, 255), s.homeLevel));
			s.moving = true;
			void watch(i);
		});

	const checkDriver = (i: number) =>
		act(async () => {
			await ready(i);
			steppers[i].driver = null;
			let ioin: number;
			try {
				ioin = asUint32((await link.request(COMMANDS.STEPPER_DRV_READ_REGISTER, i, u8(0x06))).payload);
			} catch {
				steppers[i].driver = [
					'The driver did not answer over its UART link. Check that the driver is fitted and powered, and that its address matches this channel.'
				];
				return;
			}
			const chip = ioin >>> 24;
			const lines: string[] = [];
			if (chip === 0x21) lines.push('Driver answered: a TMC2209.');
			else lines.push(`Something answered, but it reports chip version 0x${chip.toString(16)}, not a TMC2209 (0x21).`);
			try {
				const status = asUint32((await link.request(COMMANDS.STEPPER_DRV_READ_REGISTER, i, u8(0x6f))).payload);
				const raised = DRV_FLAGS.filter(([bit]) => (status >>> bit) & 1).map(([, text]) => text);
				if (raised.length) lines.push(...raised.map((t) => `Fault flag: ${t}.`));
				else lines.push('No fault flags raised.');
				lines.push('Open-load flags are only reliable while the motor turns at a moderate speed.');
			} catch {
				lines.push('The status register could not be read.');
			}
			steppers[i].driver = lines;
		});

	// ── Servos ──────────────────────────────────────────────────────────────

	// The firmware counts tenths of a degree, 0 to 1800.
	const tenths = () => clamp(servoAngle * 10, 0, 1800);

	const servoMove = (angle?: number) =>
		act(async () => {
			if (angle !== undefined) servoAngle = angle;
			const ch = servoChannel;
			if (!servoEnabled[ch]) {
				// A disabled servo takes the position without moving, so set the
				// start point first and the horn jumps there on enable.
				await link.request(COMMANDS.SERVO_MOVE_TO, ch, pack('H', tenths()));
				await link.request(COMMANDS.SERVO_SET_ENABLED, ch, u8(1));
				servoEnabled[ch] = true;
			} else {
				const accepted = (await link.request(COMMANDS.SERVO_MOVE_TO, ch, pack('H', tenths()))).payload[0];
				if (!accepted) throw new Error('That servo is still moving. Wait a moment and try again.');
			}
			servoReadout = null;
		});

	const servoRelease = () =>
		act(async () => {
			await link.request(COMMANDS.SERVO_SET_ENABLED, servoChannel, u8(0));
			servoEnabled[servoChannel] = false;
		});

	const servoRead = () =>
		act(async () => {
			servoReadout = asUint16((await link.request(COMMANDS.SERVO_GET_POSITION, servoChannel)).payload) / 10;
		});

	// ── Inputs and outputs ─────────────────────────────────────────────────

	async function readInputs() {
		const next: boolean[] = [];
		for (let c = 0; c < inputs.length; c++) {
			next.push((await link.request(COMMANDS.DIGITAL_READ, c, undefined, 1000, true)).payload[0] === 1);
		}
		inputs = next;
	}

	$effect(() => {
		if (!live || status !== 'ready') return;
		let off = false;
		(async () => {
			while (!off) {
				try {
					await readInputs();
				} catch (e) {
					notice = { tone: 'error', text: message(e) };
					live = false;
					return;
				}
				await sleep(150);
			}
		})();
		return () => {
			off = true;
		};
	});

	const setOutput = (c: number, on: boolean) =>
		act(async () => {
			await link.request(COMMANDS.DIGITAL_WRITE, c, u8(on ? 1 : 0));
			outputs[c] = { on, duty: on ? 100 : 0 };
		});

	const setPwm = (c: number, percent: number) =>
		act(async () => {
			const p = clamp(percent, 0, 100);
			await link.request(COMMANDS.DIGITAL_WRITE_PWM, c, pack('H', Math.round((p / 100) * 65535)));
			outputs[c] = { on: p > 0, duty: p };
		});

	const pingBoard = () =>
		act(async () => {
			const started = performance.now();
			await link.request(COMMANDS.PING, 0, u8(1, 2, 3, 4));
			notice = { tone: 'info', text: `The board answered in ${Math.round(performance.now() - started)} ms.` };
		});

	const reinit = () =>
		act(async () => {
			stopping++;
			await identify();
			notice = { tone: 'info', text: 'Board reset to its start state and scanned again.' };
		});

	const stamp = (t: number) => new Date(t).toLocaleTimeString([], { hour12: false });
</script>

<div class="ft">
	{#if !supported}
		<div class="note note-error">
			<p>
				This browser cannot talk to a USB serial device. Open this page in Chrome, Edge, Brave or Opera on a
				computer (Firefox, Safari and phones do not support Web Serial).
			</p>
		</div>
	{:else}
		<section class="card">
			<h3 class="card-title">Connection</h3>
			<div class="row">
				{#if status === 'ready'}
					<button class="btn" onclick={disconnect}>Disconnect</button>
					<button class="btn" onclick={pingBoard}>Ping</button>
					<button class="btn" onclick={reinit}>Reset and rescan</button>
				{:else}
					<button class="btn btn-primary" onclick={connect} disabled={status === 'connecting'}>
						{status === 'connecting' ? 'Connecting…' : 'Connect to board'}
					</button>
					<label class="field">
						<span>Board address</span>
						<input type="number" min="0" max="255" bind:value={address} class="num" />
					</label>
					<label class="check">
						<input type="checkbox" bind:checked={showAllPorts} />
						<span>Show every serial port</span>
					</label>
				{/if}
			</div>

			{#if status === 'ready' && config}
				<dl class="facts">
					<div><dt>Board</dt><dd>{config.device_name}{hw ? ` (${hw})` : ''}</dd></div>
					{#if version}
						<div>
							<dt>Firmware</dt>
							<dd>{version.firmware_version}{version.variant ? `, ${version.variant}` : ''}</dd>
						</div>
					{/if}
					<div><dt>Steppers</dt><dd>{config.stepper_count}</dd></div>
					<div><dt>Servo channels</dt><dd>{config.servo_count}</dd></div>
					<div><dt>Inputs</dt><dd>{config.digital_input_count}</dd></div>
					<div><dt>Outputs</dt><dd>{config.digital_output_count}</dd></div>
				</dl>
			{/if}
		</section>

		{#if notice}
			<div class="note note-{notice.tone}" role={notice.tone === 'error' ? 'alert' : 'status'}>
				<p>{notice.text}</p>
			</div>
		{/if}

		{#if status === 'ready' && config}
			<section class="card">
				<div class="card-head">
					<h3 class="card-title">Steppers</h3>
					{#if steppers.length}
						<button class="btn btn-danger" onclick={stopAll}>Stop all</button>
					{/if}
				</div>
				{#if !steppers.length}
					<p class="muted">This board reports no stepper channels.</p>
				{/if}
				{#each steppers as s, i (i)}
					<div class="well">
						<div class="well-head">
							<strong>{pretty(s.name)}</strong>
							<span class="muted">channel {i}</span>
							<span class="state" class:on={s.moving}>{s.moving ? 'moving' : 'stopped'}</span>
							<span class="muted mono">position {s.position ?? '?'}</span>
						</div>

						<div class="row">
							<label class="field">
								<span>Run current (0 to 31)</span>
								<input class="num" type="number" min="0" max="31" bind:value={s.irun} oninput={() => changed(i)} />
							</label>
							<label class="field">
								<span>Hold current (0 to 31)</span>
								<input class="num" type="number" min="0" max="31" bind:value={s.ihold} oninput={() => changed(i)} />
							</label>
							<label class="field">
								<span>Microsteps</span>
								<select bind:value={s.microsteps} onchange={() => changed(i)}>
									{#each MICROSTEP_CHOICES as m}<option value={m}>1/{m}</option>{/each}
								</select>
							</label>
							<button class="btn" onclick={() => act(() => applyDriver(i))}>Apply</button>
						</div>

						<div class="row">
							<label class="field">
								<span>Steps</span>
								<input class="num wide" type="number" min="1" bind:value={s.steps} />
							</label>
							<button class="btn" onclick={() => moveSteps(i, -1)}>Reverse</button>
							<button class="btn" onclick={() => moveSteps(i, 1)}>Forward</button>
						</div>

						<div class="row">
							<label class="field">
								<span>Speed (steps per second)</span>
								<input class="num wide" type="number" min="1" max="4000" bind:value={s.speed} />
							</label>
							<button class="btn" onclick={() => runAtSpeed(i, -1)}>Run reverse</button>
							<button class="btn" onclick={() => runAtSpeed(i, 1)}>Run forward</button>
							<button class="btn btn-danger" onclick={() => stopStepper(i)}>Stop</button>
						</div>

						<div class="row">
							<button class="btn" onclick={() => checkDriver(i)}>Check driver</button>
							<button class="btn" onclick={() => act(() => refresh(i))}>Read position</button>
							<button class="btn" onclick={() => zeroPosition(i)}>Set position to 0</button>
							<button class="btn" onclick={() => cutCurrent(i)}>Release motor</button>
						</div>

						{#if s.driver}
							<ul class="results">
								{#each s.driver as line}<li>{line}</li>{/each}
							</ul>
						{/if}

						{#if config.digital_input_count > 0}
							<details>
								<summary>Home against a limit switch</summary>
								<p class="muted">
									The motor turns until the chosen input reaches the chosen level, then stops and its
									position becomes 0. If the input already reads that level, it stops without moving. Press Stop if it never gets there.
								</p>
								<div class="row">
									<label class="field">
										<span>Input</span>
										<select bind:value={s.homeInput}>
											{#each inputs as _, c}<option value={c}>Input {c}{pins ? ` (GPIO ${pins.inputs[c]})` : ''}</option>{/each}
										</select>
									</label>
									<label class="field">
										<span>Stop when it reads</span>
										<select bind:value={s.homeLevel}>
											<option value={0}>Low</option>
											<option value={1}>High</option>
										</select>
									</label>
									<label class="field">
										<span>Speed (negative turns the other way)</span>
										<input class="num wide" type="number" min="-4000" max="4000" bind:value={s.homeSpeed} />
									</label>
									<button class="btn" onclick={() => homeStepper(i)}>Home</button>
								</div>
							</details>
						{/if}
					</div>
				{/each}
			</section>

			<section class="card">
				<h3 class="card-title">Servos</h3>
				{#if config.servo_count === 0}
					<p class="muted">
						No servo controller (PCA9685) answered at I2C address 0x40, so there are no servo channels.
						Check its wiring and power, then use Reset and rescan.
					</p>
				{:else}
					<div class="well">
						<div class="row">
							<label class="field">
								<span>Channel</span>
								<select bind:value={servoChannel}>
									{#each Array(config.servo_count) as _, c}<option value={c}>{c}{servoEnabled[c] ? ' (on)' : ''}</option>{/each}
								</select>
							</label>
							<label class="field grow">
								<span>Angle: {servoAngle}°</span>
								<input type="range" min="0" max="180" step="1" bind:value={servoAngle} />
							</label>
						</div>
						<div class="row">
							<button class="btn btn-primary" onclick={() => servoMove()}>
								{servoEnabled[servoChannel] ? 'Move to angle' : 'Switch on at this angle'}
							</button>
							<button class="btn" onclick={() => servoMove(0)}>0°</button>
							<button class="btn" onclick={() => servoMove(90)}>90°</button>
							<button class="btn" onclick={() => servoMove(180)}>180°</button>
							<button class="btn" onclick={servoRelease}>Release</button>
							<button class="btn" onclick={servoRead}>Read position</button>
							{#if servoReadout !== null}<span class="muted mono">{servoReadout}°</span>{/if}
						</div>
					</div>
				{/if}
			</section>

			<section class="card">
				<div class="card-head">
					<h3 class="card-title">Inputs</h3>
					<button class="btn" onclick={() => act(readInputs)}>Read</button>
					<label class="check">
						<input type="checkbox" bind:checked={live} />
						<span>Live</span>
					</label>
				</div>
				{#if !inputs.length}
					<p class="muted">This board reports no digital inputs.</p>
				{:else}
					<div class="chips">
						{#each inputs as value, c}
							<div class="chip">
								<span>Input {c}{pins ? ` (GPIO ${pins.inputs[c]})` : ''}</span>
								<strong class:high={value === true} class:low={value === false}>
									{value === null ? 'not read' : value ? 'High' : 'Low'}
								</strong>
							</div>
						{/each}
					</div>
					<p class="muted">Inputs are pulled up, so one with nothing connected reads High.</p>
				{/if}
			</section>

			<section class="card">
				<h3 class="card-title">Outputs</h3>
				{#if !outputs.length}
					<p class="muted">This board reports no digital outputs.</p>
				{/if}
				{#each outputs as o, c}
					<div class="well">
						<div class="row">
							<strong>Output {c}{pins ? ` (GPIO ${pins.outputs[c]})` : ''}</strong>
							<span class="state" class:on={o.on}>{o.on ? (o.duty === 100 ? 'on' : `${o.duty}%`) : 'off'}</span>
							<button class="btn" onclick={() => setOutput(c, true)}>On</button>
							<button class="btn" onclick={() => setOutput(c, false)}>Off</button>
							<label class="field grow">
								<span>Brightness or duty</span>
								<input
									type="range"
									min="0"
									max="100"
									step="5"
									value={o.duty}
									onchange={(e) => setPwm(c, Number(e.currentTarget.value))}
								/>
							</label>
						</div>
					</div>
				{/each}
			</section>
		{/if}

		<section class="card">
			<div class="card-head">
				<h3 class="card-title">Traffic</h3>
				<button class="btn" onclick={() => (log = [])}>Clear</button>
			</div>
			<div class="log mono" bind:this={logEl} role="log" aria-label="Messages to and from the board">
				{#each log as entry}
					<div class="log-{entry.dir}"><span class="muted">{stamp(entry.t)}</span> {entry.dir === 'tx' ? '→' : entry.dir === 'rx' ? '←' : '·'} {entry.text}</div>
				{:else}
					<div class="muted">Nothing yet.</div>
				{/each}
			</div>
		</section>
	{/if}
</div>

<style>
	.ft {
		display: grid;
		gap: 16px;
		margin: 24px 0;
		font-size: 0.9375rem;
		line-height: 1.4;
	}
	.card {
		background: var(--surface);
		border: 1px solid var(--line);
		padding: 16px;
		display: grid;
		gap: 12px;
	}
	.card-head {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.card-head :global(.btn:first-of-type) {
		margin-left: auto;
	}
	.card-title {
		margin: 0;
		font-size: 1.0625rem;
	}
	.well {
		background: var(--bg);
		padding: 12px;
		display: grid;
		gap: 12px;
	}
	.well-head {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 4px 12px;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: 8px 12px;
	}
	.field {
		display: grid;
		gap: 2px;
		font-size: 0.875rem;
		color: var(--muted);
	}
	.field.grow {
		flex: 1 1 200px;
	}
	.check {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.875rem;
	}
	input.num,
	select {
		font: inherit;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 1px;
		padding: 6px 8px;
		width: 7rem;
	}
	input.num.wide {
		width: 9rem;
	}
	select {
		width: auto;
		min-width: 7rem;
	}
	input:focus-visible,
	select:focus-visible,
	.btn:focus-visible,
	summary:focus-visible {
		outline: 2px solid var(--primary);
		outline-offset: 1px;
	}
	.btn {
		font: inherit;
		font-size: 0.875rem;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 1px;
		padding: 6px 12px;
		cursor: pointer;
	}
	.btn:hover:not(:disabled) {
		background: var(--bg);
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.btn-primary {
		color: var(--color-primary-contrast);
		background: var(--primary);
		border-color: var(--primary);
	}
	.btn-primary:hover:not(:disabled) {
		background: var(--primary-hover);
	}
	.btn-danger {
		color: var(--error);
		border-color: var(--error-border);
	}
	.btn-danger:hover:not(:disabled) {
		background: var(--error-bg);
	}
	.muted {
		color: var(--muted);
		font-size: 0.875rem;
		margin: 0;
	}
	.mono {
		font-family: var(--font-mono);
	}
	.state {
		font-size: 0.8125rem;
		padding: 0 6px;
		background: var(--surface);
		color: var(--muted);
	}
	.state.on {
		background: var(--info-bg);
		color: var(--info);
	}
	.note {
		padding: 10px 14px;
	}
	.note p {
		margin: 0;
	}
	.note-error {
		background: var(--error-bg);
		border-left: 3px solid var(--color-danger);
	}
	.note-info {
		background: var(--info-bg);
		border-left: 3px solid var(--color-info);
	}
	.facts {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 24px;
		margin: 0;
	}
	.facts div {
		display: flex;
		gap: 6px;
	}
	.facts dt {
		color: var(--muted);
	}
	.facts dd {
		margin: 0;
	}
	.results {
		margin: 0;
		padding-left: 20px;
		list-style: disc;
	}
	details summary {
		cursor: pointer;
	}
	details[open] summary {
		margin-bottom: 8px;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.chip {
		background: var(--bg);
		padding: 8px 12px;
		display: grid;
		gap: 2px;
		min-width: 9rem;
	}
	.chip strong.high {
		color: var(--ok);
	}
	.chip strong.low {
		color: var(--info);
	}
	.log {
		background: var(--bg);
		padding: 8px 12px;
		max-height: 14rem;
		overflow: auto;
		font-size: 0.8125rem;
		line-height: 1.5;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.log-error {
		color: var(--error);
	}
	input[type='range'] {
		width: 100%;
		accent-color: var(--primary);
	}
</style>
