<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
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
		amplitudeDeg: 6,
		cycles: 12,
		speed: 5000,
		acceleration: 100000
	};

	type JitterPreset = {
		name: string;
		blurb: string;
		amplitudeDeg: number;
		cycles: number;
		speed: number;
		acceleration: number;
	};

	// Amplitude is per-stroke MOTOR degrees (before gear reduction); the big gear
	// ratio means even "medium" motor amplitudes are a small rotor swing. Speeds
	// in µsteps/s (firmware caps at 60000); accel in µsteps/s². "Heavy Stuck"
	// (6° / 12c / 5000 / 100000) is the reference that visibly worked — medium
	// travel, medium strength, medium length. The others are variants around it:
	// travel = amplitude, length = cycles, strength = speed + accel.
	const PRESETS: JitterPreset[] = [
		{ name: 'Heavy stuck', blurb: 'Reference: medium everything, the one that worked', amplitudeDeg: 6, cycles: 12, speed: 5000, acceleration: 100000 },
		{ name: 'Quick stuck', blurb: 'Same force & travel, shorter', amplitudeDeg: 6, cycles: 6, speed: 5000, acceleration: 100000 },
		{ name: 'Brief stuck', blurb: 'Same force & travel, very short burst', amplitudeDeg: 6, cycles: 3, speed: 5000, acceleration: 100000 },
		{ name: 'Sharp & short', blurb: 'Stronger jerk, shorter', amplitudeDeg: 6, cycles: 6, speed: 6500, acceleration: 180000 },
		{ name: 'Hard snap', blurb: 'Max jerk, tiny burst', amplitudeDeg: 6, cycles: 3, speed: 7000, acceleration: 220000 },
		{ name: 'Soft & long', blurb: 'Softer but longer', amplitudeDeg: 5, cycles: 30, speed: 3500, acceleration: 55000 },
		{ name: 'Gentle marathon', blurb: 'Very soft, very long', amplitudeDeg: 4, cycles: 50, speed: 3000, acceleration: 45000 },
		{ name: 'Big travel', blurb: 'More throw, medium length', amplitudeDeg: 9, cycles: 12, speed: 5000, acceleration: 110000 },
		{ name: 'Big & brief', blurb: 'Big throw, short', amplitudeDeg: 9, cycles: 5, speed: 6000, acceleration: 150000 },
		{ name: 'Big & hard', blurb: 'Big throw, strong jerk', amplitudeDeg: 9, cycles: 8, speed: 6500, acceleration: 200000 },
		{ name: 'Max shake', blurb: 'Largest throw, strong', amplitudeDeg: 13, cycles: 12, speed: 6500, acceleration: 190000 },
		{ name: 'Wide & soft', blurb: 'Big throw but gentle, long', amplitudeDeg: 9, cycles: 16, speed: 3500, acceleration: 55000 },
		{ name: 'Fast buzz', blurb: 'Medium throw, fast & long', amplitudeDeg: 6, cycles: 24, speed: 6000, acceleration: 150000 },
		{ name: 'Strong & long', blurb: 'Strong and persistent', amplitudeDeg: 8, cycles: 30, speed: 6000, acceleration: 140000 }
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

<svelte:head><title>Sorter - Jitter test</title></svelte:head>

<PageHeader
	title="Jitter test"
	description="A short, sharp back-and-forth on a stepper that breaks static friction: enough to nudge a stuck piece off a C channel without a violent shake. It runs on the firmware's real-time core and ends where it started."
/>

<Panel title="Motor">
	<div class="max-w-64">
		<Select
			label="Motor"
			bind:value={settings.stepper}
			options={STEPPERS.map((key) => ({ value: key, label: stepperLabels[key] }))}
		/>
	</div>
</Panel>

<Panel
	title="Presets"
	description="A preset fills in the settings below; then press Jitter. Amplitudes are at the motor: the rotor moves about {gearRatio.toFixed(1)} times less."
	flush
>
	<div
		class="grid grid-cols-1 gap-px border-t border-line bg-line sm:grid-cols-3 sm:[&>:last-child:nth-child(3n+1)]:col-span-3 sm:[&>:last-child:nth-child(3n+2)]:col-span-2"
	>
		{#each PRESETS as p (p.name)}
			{@const selected =
				settings.amplitudeDeg === p.amplitudeDeg &&
				settings.cycles === p.cycles &&
				settings.speed === p.speed &&
				settings.acceleration === p.acceleration}
			<!-- The cell is opaque, so the chosen tint sits on the surface and not on the lines between cells. -->
			<button type="button" aria-pressed={selected} onclick={() => applyPreset(p)} class="bg-surface text-left">
				<span
					class="flex h-full flex-col gap-0.5 px-(--pad-panel) py-(--pad-row) transition-colors {selected
						? 'bg-primary-soft'
						: 'hover:bg-well'}"
				>
					<span class="text-sm font-medium {selected ? 'text-primary-ink' : 'text-ink'}">{p.name}</span>
					<span class="text-sm text-ink-muted">{p.blurb}</span>
					<span class="num text-sm text-ink-muted">
						±{p.amplitudeDeg}°, {p.cycles} cycles, {p.speed} µsteps/s, {(p.acceleration / 1000).toFixed(0)}k
					</span>
				</span>
			</button>
		{/each}
	</div>
</Panel>

<Panel title="Settings">
	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
		<Field
			label="Amplitude"
			for="jitter-amplitude"
			help="About {outputAmplitudeDeg.toFixed(2)}° at the rotor (gear ratio {gearRatio.toFixed(2)}:1)."
		>
			<Input id="jitter-amplitude" type="number" step={0.1} bind:value={settings.amplitudeDeg} unit="° a stroke" />
		</Field>
		<Field label="Cycles" for="jitter-cycles" help="Back-and-forths.">
			<Input id="jitter-cycles" type="number" step={1} bind:value={settings.cycles} />
		</Field>
		<Field label="Speed" for="jitter-speed">
			<Input id="jitter-speed" type="number" step={100} bind:value={settings.speed} unit="µsteps/s" />
		</Field>
		<Field label="Acceleration" for="jitter-accel" help="Higher is a sharper jerk each stroke.">
			<Input id="jitter-accel" type="number" step={5000} bind:value={settings.acceleration} unit="µsteps/s²" />
		</Field>
	</div>
	{#snippet footer()}
		<Button variant="ghost" class="mr-auto" onclick={resetDefaults}>Back to the defaults</Button>
		<Button variant="danger" onclick={stopStepper}>Stop</Button>
		<Button variant="primary" loading={busy} onclick={runJitter}>Jitter</Button>
	{/snippet}
</Panel>

{#if statusMsg}
	<Alert tone="info">{statusMsg}</Alert>
{/if}
{#if errorMsg}
	<Alert tone="danger">{errorMsg}</Alert>
{/if}
