<!--
	How a StallGuard sweep moves the motor, for someone who wants it other than
	the steps do it: the motion, direction and duration, a label, the angles or
	pulses that motion needs, and the cruise TSTEP the sweep filters by. The
	speed is not here: it belongs to the whole tuning, set in its first step.
	It sits in the tab's Expert tools.
-->
<script lang="ts">
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import type { Profile, SweepOptions } from '$lib/settings/stallguard';

	let {
		options = $bindable(),
		motor,
		autoCruise
	}: {
		options: SweepOptions;
		motor: string;
		// The cruise TSTEP that follows the speed, used while the field is empty.
		autoCruise: number;
	} = $props();

	const directionOptions: { value: 'cw' | 'ccw'; label: string }[] = [
		{ value: 'cw', label: 'Clockwise' },
		{ value: 'ccw', label: 'Counterclockwise' }
	];
	// Going to random angles needs the chute's endstops and angles; no other motor has them.
	const profileOptions = $derived<{ value: Profile; label: string }[]>([
		{ value: 'constant', label: 'Constant spin' },
		...(motor === 'chute'
			? [{ value: 'chute_random' as const, label: 'Chute: random go-to-angle' }]
			: []),
		{ value: 'pulsed', label: 'Pulsed with jitter' }
	]);
	const cruiseHelp = $derived(
		`Only motion at or under this TSTEP (lower is faster) counts toward a recording's own readings, since speeding up, slowing down and reversing dip them even unloaded. Empty follows the speed: ${autoCruise}. The speed floor saved in step 4 is measured from the recordings, not taken from here.`
	);
</script>

<div class="grid grid-cols-1 gap-4 px-(--pad-panel) pt-1 pb-4 sm:grid-cols-2 lg:grid-cols-3">
	<Field label="Motion" for="sw-profile">
		<Select id="sw-profile" bind:value={options.profile} options={profileOptions} />
	</Field>
	<Field label="Direction" for="sw-direction">
		<Select id="sw-direction" bind:value={options.direction} options={directionOptions} />
	</Field>
	<Field label="Duration" for="sw-duration">
		<Input id="sw-duration" type="number" unit="s" bind:value={options.duration} />
	</Field>
	<Field label="Label" for="sw-label" help="Optional. Names the recordings in the list.">
		<Input id="sw-label" bind:value={options.label} />
	</Field>
	{#if options.profile === 'chute_random'}
		<Field label="Min angle" for="sw-min">
			<Input id="sw-min" type="number" unit="° output" bind:value={options.chuteMinDeg} />
		</Field>
		<Field label="Max angle" for="sw-max">
			<Input id="sw-max" type="number" unit="° output" bind:value={options.chuteMaxDeg} />
		</Field>
		<Field label="Min angle change" for="sw-delta">
			<Input id="sw-delta" type="number" unit="°" bind:value={options.minDeltaDeg} />
		</Field>
		<p class="text-sm text-ink-muted sm:col-span-2 lg:col-span-3">
			Random go-to-angle between the min and max output angle (clamped to the chute's safe travel,
			345° at most), turning straight back on each arrival. Homes the chute first if needed, so it
			moves on absolute angles and can never reach an endstop.
		</p>
	{:else if options.profile === 'pulsed'}
		<Field label="Pulse size" for="sw-pulse">
			<Input id="sw-pulse" type="number" unit="° motor" bind:value={options.pulseDeg} />
		</Field>
		<Field label="Dwell" for="sw-dwell">
			<Input id="sw-dwell" type="number" unit="ms" bind:value={options.dwellMs} />
		</Field>
		<Field label="Jitter every" for="sw-jitter" help="0 turns the jitter off.">
			<Input id="sw-jitter" type="number" unit="pulses" bind:value={options.jitterEvery} />
		</Field>
		<p class="text-sm text-ink-muted sm:col-span-2 lg:col-span-3">
			Separate pulses with a dwell between them, as the rotors and carousel really run, and an
			unstick jitter every few pulses. Only the moving phases are sampled.
		</p>
	{/if}
	<Field label="Cruise TSTEP" for="sw-tstep" help={cruiseHelp} class="sm:col-span-2">
		<Input
			id="sw-tstep"
			type="number"
			placeholder={String(autoCruise)}
			bind:value={options.cruiseTstep}
			class="w-56"
		/>
	</Field>
	<div class="sm:col-span-2 lg:col-span-3">
		<Checkbox bind:checked={options.enterToRun}>
			Enter starts the recording of the step that is open
		</Checkbox>
	</div>
</div>
