<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import NudgeControl from '$lib/components/ui/NudgeControl.svelte';
	import Menu from '$lib/components/ui/Menu.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import { onMount } from 'svelte';
	import {
		DIRECTION_WORDS,
		STEPPER_GEAR_RATIOS,
		loadStoredStepperPulseSetting,
		persistStoredStepperPulseSetting
	} from '$lib/settings/stepper-control';
	import type { StepperKey } from '$lib/settings/stations';

	let { stepperKey }: { stepperKey: StepperKey } = $props();

	const machine = getMachineContext();

	// Left is counterclockwise and right is clockwise, as the arrows point.
	type ChannelSide = 'left' | 'right';

	// How far each press turns the channel: 10° unless this browser kept another
	// amount for this channel. Any amount above 0 up to one full turn.
	const JOG_FIELD = 'dashboardJogDegrees';
	const DEFAULT_JOG_DEGREES = 10;
	const MAX_JOG_DEGREES = 360;

	function readStoredJogDegrees(): number {
		const stored = loadStoredStepperPulseSetting<number>(
			stepperKey,
			JOG_FIELD,
			DEFAULT_JOG_DEGREES
		);
		return Number.isFinite(stored) && stored > 0 && stored <= MAX_JOG_DEGREES
			? stored
			: DEFAULT_JOG_DEGREES;
	}

	let jogDegrees = $state(readStoredJogDegrees());
	let pendingSide = $state<ChannelSide | null>(null);
	let errorMessage = $state<string | null>(null);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	async function readErrorMessage(res: Response): Promise<string> {
		try {
			const data = await res.json();
			if (typeof data?.detail === 'string') return data.detail;
			if (typeof data?.message === 'string') return data.message;
		} catch {
			// fall through to text
		}
		try {
			const text = await res.text();
			if (text) return text;
		} catch {
			// fall through to status
		}
		return `Request failed with status ${res.status}`;
	}

	function humanizeStepperError(message: string): string {
		if (message.includes('Controller not initialized')) {
			return 'Hardware not started. Press Home in the dashboard first.';
		}
		return message;
	}

	// The shakes a recovery procedure runs (backend recovery/profiles.py), by
	// hand: the same list and the same code.
	type Shake = { key: string; label: string; blurb: string };
	let shakes = $state<Shake[]>([]);
	let shaking = $state(false);

	onMount(() => {
		void (async () => {
			try {
				const res = await fetch(`${currentBackendBaseUrl()}/api/recovery/shakes`);
				if (res.ok) shakes = ((await res.json()).shakes ?? []) as Shake[];
			} catch {
				// no menu without the list
			}
		})();
	});

	async function shake(profile: string) {
		if (shaking) return;
		shaking = true;
		errorMessage = null;
		try {
			const params = new URLSearchParams({ stepper: stepperKey, profile });
			const res = await fetch(`${currentBackendBaseUrl()}/api/recovery/shake?${params.toString()}`, {
				method: 'POST'
			});
			if (!res.ok) {
				throw new Error(humanizeStepperError(await readErrorMessage(res)));
			}
		} catch (e: any) {
			errorMessage = e?.message ?? 'Could not shake the channel';
		} finally {
			shaking = false;
		}
	}

	async function moveOutputDegrees(side: ChannelSide, output_degrees: number) {
		if (pendingSide) return;
		pendingSide = side;
		errorMessage = null;
		try {
			const gear_ratio = STEPPER_GEAR_RATIOS[stepperKey] ?? 1;
			const speed = loadStoredStepperPulseSetting<number>(stepperKey, 'pulseSpeed', 800);
			const params = new URLSearchParams({
				stepper: stepperKey,
				degrees: String(output_degrees * gear_ratio),
				speed: String(speed)
			});
			const res = await fetch(
				`${currentBackendBaseUrl()}/stepper/move-degrees?${params.toString()}`,
				{ method: 'POST' }
			);
			if (!res.ok) {
				throw new Error(humanizeStepperError(await readErrorMessage(res)));
			}
		} catch (e: any) {
			errorMessage = e?.message ?? 'Could not move channel';
		} finally {
			pendingSide = null;
		}
	}
</script>

{#if errorMessage}
	<span class="max-w-44 truncate text-sm text-danger-ink" title={errorMessage}>{errorMessage}</span>
{/if}
<!-- The arrows turn the channel by the amount between them; the amount opens the
     presets (10°, 180°) and a field for any other. -->
<NudgeControl
	bind:value={jogDegrees}
	presets={[10, 180]}
	max={MAX_JOG_DEGREES}
	label="Turn the channel"
	leftLabel="Turn the channel {jogDegrees}° {DIRECTION_WORDS.ccw}"
	rightLabel="Turn the channel {jogDegrees}° {DIRECTION_WORDS.cw}"
	amountLabel="Each press turns"
	busy={pendingSide}
	onnudge={(side) => void moveOutputDegrees(side, side === 'left' ? -jogDegrees : jogDegrees)}
	onchange={(degrees) => persistStoredStepperPulseSetting(stepperKey, JOG_FIELD, degrees)}
/>
{#if shakes.length}
	<Menu
		label="Shake the channel"
		items={shakes.map((s) => ({ label: s.label, hint: s.blurb, onselect: () => void shake(s.key) }))}
	>
		{#snippet trigger(props)}
			<Button {...props} size="sm" loading={shaking}>Shake</Button>
		{/snippet}
	</Menu>
{/if}
