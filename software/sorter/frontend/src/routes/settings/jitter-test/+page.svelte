<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import { Alert, Button, Input } from '$lib/components/primitives';
	import { STEPPER_GEAR_RATIOS } from '$lib/settings/stepper-control';
	import { stepperLabels, type StepperKey } from '$lib/settings/stations';

	const manager = getMachinesContext();

	const STEPPERS: StepperKey[] = ['c_channel_1', 'c_channel_2', 'c_channel_3', 'c_channel_4', 'carousel', 'chute'];

	type JitterSettings = {
		stepper: StepperKey;
		amplitudeDeg: number;
		cycles: number;
		speed: number;
		acceleration: number;
	};

	const DEFAULTS: JitterSettings = {
		stepper: 'c_channel_1',
		amplitudeDeg: 2,
		cycles: 20,
		speed: 4000,
		acceleration: 60000
	};

	type JitterPreset = {
		name: string;
		blurb: string;
		amplitudeDeg: number;
		cycles: number;
		speed: number;
		acceleration: number;
	};

	// Amplitude is per-stroke MOTOR degrees (before gear reduction). Speeds in
	// µsteps/s (firmware caps at 60000); accel in µsteps/s². Higher accel = sharper
	// jerk; small amplitude keeps total travel tiny.
	const PRESETS: JitterPreset[] = [
		{ name: 'Gentle Tap', blurb: 'Soft, low-energy nudge', amplitudeDeg: 1, cycles: 5, speed: 2000, acceleration: 30000 },
		{ name: 'Default', blurb: 'Balanced starting point', amplitudeDeg: 2, cycles: 20, speed: 4000, acceleration: 60000 },
		{ name: 'Micro Dither', blurb: 'Tiny, very fast flutter', amplitudeDeg: 0.5, cycles: 30, speed: 3000, acceleration: 60000 },
		{ name: 'Fast Buzz', blurb: 'High-frequency small strokes', amplitudeDeg: 1, cycles: 40, speed: 5000, acceleration: 80000 },
		{ name: 'Sharp Snap', blurb: 'Hard jerk, short throw', amplitudeDeg: 1.5, cycles: 15, speed: 4000, acceleration: 120000 },
		{ name: 'Hard Kick', blurb: 'Aggressive, few strokes', amplitudeDeg: 3, cycles: 8, speed: 6000, acceleration: 150000 },
		{ name: 'Wide Nudge', blurb: 'Bigger swing, moderate', amplitudeDeg: 5, cycles: 10, speed: 4000, acceleration: 40000 },
		{ name: 'Slow Rock', blurb: 'Slow, gentle rocking', amplitudeDeg: 4, cycles: 6, speed: 1500, acceleration: 20000 },
		{ name: 'Quick Triple', blurb: 'Three brisk shakes', amplitudeDeg: 2, cycles: 3, speed: 4000, acceleration: 80000 },
		{ name: 'Long Shake', blurb: 'Sustained, persistent', amplitudeDeg: 2, cycles: 60, speed: 4000, acceleration: 60000 },
		{ name: 'Heavy Stuck', blurb: 'For a really jammed piece', amplitudeDeg: 6, cycles: 12, speed: 5000, acceleration: 100000 },
		{ name: 'Endurance', blurb: 'Long, fast, persistent buzz', amplitudeDeg: 1.5, cycles: 100, speed: 5000, acceleration: 90000 }
	];

	const STORAGE_KEY = 'jitter-test:settings';

	function loadSettings(): JitterSettings {
		try {
			if (typeof localStorage === 'undefined') return { ...DEFAULTS };
			const raw = localStorage.getItem(STORAGE_KEY);
			if (!raw) return { ...DEFAULTS };
			return { ...DEFAULTS, ...JSON.parse(raw) };
		} catch {
			return { ...DEFAULTS };
		}
	}

	let settings = $state<JitterSettings>(loadSettings());
	let busy = $state(false);
	let statusMsg = $state<string | null>(null);
	let errorMsg = $state<string | null>(null);

	$effect(() => {
		try {
			localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
		} catch {
			/* ignore persistence failures */
		}
	});

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	const gearRatio = $derived(STEPPER_GEAR_RATIOS[settings.stepper] ?? 1);
	const outputAmplitudeDeg = $derived(settings.amplitudeDeg / gearRatio);

	async function readError(res: Response): Promise<string> {
		try {
			const data = await res.json();
			if (typeof data?.detail === 'string') return data.detail;
			if (typeof data?.message === 'string') return data.message;
		} catch {
			/* fall through */
		}
		return `Request failed with status ${res.status}`;
	}

	async function runJitter() {
		busy = true;
		errorMsg = null;
		statusMsg = null;
		try {
			const params = new URLSearchParams({
				stepper: settings.stepper,
				amplitude_deg: String(settings.amplitudeDeg),
				cycles: String(settings.cycles),
				speed: String(settings.speed),
				acceleration: String(settings.acceleration)
			});
			const res = await fetch(`${currentBackendBaseUrl()}/stepper/jitter?${params.toString()}`, {
				method: 'POST'
			});
			if (!res.ok) {
				throw new Error(await readError(res));
			}
			const payload = await res.json();
			statusMsg = `Jittering ${stepperLabels[settings.stepper]}: ${payload.cycles} cycles of ±${settings.amplitudeDeg}° motor (~${payload.estimated_duration_s}s, ${payload.amplitude_microsteps} µsteps/stroke).`;
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	async function stopStepper() {
		errorMsg = null;
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/stepper/stop?stepper=${encodeURIComponent(settings.stepper)}`,
				{ method: 'POST' }
			);
			if (!res.ok) throw new Error(await readError(res));
			statusMsg = `Stopped ${stepperLabels[settings.stepper]}.`;
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : String(e);
		}
	}

	function resetDefaults() {
		settings = { ...DEFAULTS, stepper: settings.stepper };
	}

	function applyPreset(p: JitterPreset) {
		settings = {
			stepper: settings.stepper,
			amplitudeDeg: p.amplitudeDeg,
			cycles: p.cycles,
			speed: p.speed,
			acceleration: p.acceleration
		};
	}
</script>

<div class="mx-auto flex max-w-3xl flex-col gap-6 p-6">
	<header class="flex flex-col gap-1">
		<h1 class="text-xl font-semibold tracking-wide">Jitter Test</h1>
		<p class="text-sm text-neutral-400">
			Fire a short, sharp back-and-forth oscillation on a stepper to break static friction —
			tuned to nudge a stuck piece off a C channel without a violent shake. The motion runs on the
			firmware's real-time core and returns to the starting position.
		</p>
	</header>

	<SectionCard title="Motor">
		<div class="flex flex-wrap gap-2">
			{#each STEPPERS as key (key)}
				<Button
					variant={settings.stepper === key ? 'primary' : 'secondary'}
					size="sm"
					onclick={() => (settings.stepper = key)}
				>
					{stepperLabels[key]}
				</Button>
			{/each}
		</div>
	</SectionCard>

	<SectionCard title="Presets">
		<p class="mb-3 text-sm text-neutral-400">
			Click a scenario to load its parameters below, then press Jitter. Amplitudes are motor
			degrees; the rotor moves ~{gearRatio.toFixed(1)}× less.
		</p>
		<div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
			{#each PRESETS as p (p.name)}
				{@const selected =
					settings.amplitudeDeg === p.amplitudeDeg &&
					settings.cycles === p.cycles &&
					settings.speed === p.speed &&
					settings.acceleration === p.acceleration}
				<button
					type="button"
					onclick={() => applyPreset(p)}
					class="flex flex-col gap-0.5 border p-2 text-left transition-colors {selected
						? 'border-primary bg-primary/10'
						: 'border-neutral-700/40 hover:border-neutral-500'}"
				>
					<span class="text-sm font-semibold">{p.name}</span>
					<span class="text-sm text-neutral-400">{p.blurb}</span>
					<span class="text-xs text-neutral-500"
						>±{p.amplitudeDeg}° · {p.cycles}c · {p.speed} · {(p.acceleration / 1000).toFixed(0)}k</span
					>
				</button>
			{/each}
		</div>
	</SectionCard>

	<SectionCard title="Parameters">
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
			<label class="flex flex-col gap-1">
				<span class="text-sm font-medium">Amplitude (motor °/stroke)</span>
				<Input type="number" step="0.1" bind:value={settings.amplitudeDeg} />
				<span class="text-sm text-neutral-400">
					≈ {outputAmplitudeDeg.toFixed(2)}° at the rotor (gear {gearRatio.toFixed(2)}:1)
				</span>
			</label>

			<label class="flex flex-col gap-1">
				<span class="text-sm font-medium">Cycles (back-and-forths)</span>
				<Input type="number" step="1" bind:value={settings.cycles} />
			</label>

			<label class="flex flex-col gap-1">
				<span class="text-sm font-medium">Speed (µsteps/s)</span>
				<Input type="number" step="100" bind:value={settings.speed} />
			</label>

			<label class="flex flex-col gap-1">
				<span class="text-sm font-medium">Acceleration (µsteps/s²)</span>
				<Input type="number" step="5000" bind:value={settings.acceleration} />
				<span class="text-sm text-neutral-400">Higher accel = sharper jerk per stroke.</span>
			</label>
		</div>
	</SectionCard>

	<div class="flex flex-wrap items-center gap-3">
		<Button variant="primary" size="md" loading={busy} onclick={runJitter}>Jitter</Button>
		<Button variant="danger" size="md" onclick={stopStepper}>Stop</Button>
		<Button variant="ghost" size="sm" onclick={resetDefaults}>Reset defaults</Button>
	</div>

	{#if statusMsg}
		<Alert variant="info">{statusMsg}</Alert>
	{/if}
	{#if errorMsg}
		<Alert variant="danger">{errorMsg}</Alert>
	{/if}
</div>
