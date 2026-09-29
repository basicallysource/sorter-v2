<!--
	The other settings pages. The steppers show how a hardware page is laid
	out; the rest are outside this example.
-->
<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Square from '@lucide/svelte/icons/square';
	import Settings from '@lucide/svelte/icons/settings';
	import { page } from '$app/state';
	import Panel from '$lib/components/Panel.svelte';
	import Button from '$lib/components/Button.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import SettingRow from '$lib/components/SettingRow.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import { labelFor } from '../nav';

	const steppers = ['c-channel-1', 'c-channel-2', 'c-channel-3', 'chute'];
	const section = $derived(page.params.section ?? '');
	const title = $derived(labelFor(section) ?? 'Settings');

	let moveBy = $state<'duration' | 'degrees'>('degrees');
	let degrees = $state(5);
	let seconds = $state(1);
	let speed = $state(800);
	let current = $state(900);
	let microsteps = $state('16');
	let threshold = $state(40);
</script>

<svelte:head><title>{title} · Settings · Example app</title></svelte:head>

<div class="mb-2">
	<h1 class="text-xl font-semibold tracking-tight text-ink">{title}</h1>
	{#if steppers.includes(section)}
		<p class="mt-1 text-sm text-ink-muted">A stepper: move it by hand, and set its driver.</p>
	{/if}
</div>

{#if steppers.includes(section)}
	<Panel flush>
		<div class="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
			<div class="flex items-center gap-2">
				<span class="text-base font-semibold text-ink">Position</span>
				<Badge tone="neutral">Idle</Badge>
			</div>
			<div class="num text-sm text-ink-muted">0.0° · 0 µs</div>
		</div>
		<div class="divide-y divide-line border-t border-line">
			<div class="flex flex-col gap-4 px-5 py-4">
				<div>
					<div class="text-sm font-medium text-ink">Jog</div>
					<p class="mt-0.5 text-sm text-ink-muted">The arrow keys also move this stepper.</p>
				</div>
				<div class="flex flex-wrap gap-2">
					<Button icon={ChevronLeft}>Counterclockwise</Button>
					<Button icon={Square}>Stop</Button>
					<Button>Clockwise<ChevronRight size={16} /></Button>
				</div>
				<div class="flex flex-wrap items-end gap-4">
					<div class="flex flex-col gap-1.5">
						<span class="text-sm font-medium text-ink">Move by</span>
						<SegmentedControl
							label="Move by"
							bind:value={moveBy}
							options={[
								{ value: 'duration', label: 'Duration' },
								{ value: 'degrees', label: 'Degrees' }
							]}
						/>
					</div>
					{#if moveBy === 'degrees'}
						<Field label="Degrees at the output" for="degrees">
							<Input id="degrees" type="number" bind:value={degrees} unit="°" class="w-28" />
						</Field>
					{:else}
						<Field label="Duration" for="seconds">
							<Input id="seconds" type="number" bind:value={seconds} unit="s" class="w-28" />
						</Field>
					{/if}
					<Field label="Speed" for="speed">
						<Input id="speed" type="number" bind:value={speed} unit="steps/s" class="w-36" />
					</Field>
				</div>
				<p class="text-sm text-ink-muted tabular-nums">
					Ratio 10.83:1, so {degrees}° at the output is {(degrees * 10.83).toFixed(1)}° at the
					motor.
				</p>
			</div>
			<Disclosure title="Driver settings" help="Current, microsteps, stall detection">
				<div class="divide-y divide-line pl-6">
					<SettingRow label="Run current" help="Higher holds better and runs hotter." for="current">
						<Input id="current" type="number" bind:value={current} unit="mA" class="w-28" />
					</SettingRow>
					<SettingRow label="Microsteps" for="microsteps">
						<Select
							id="microsteps"
							bind:value={microsteps}
							options={['8', '16', '32', '64'].map((m) => ({ value: m, label: m }))}
							class="w-28"
						/>
					</SettingRow>
					<SettingRow
						label="StallGuard threshold"
						help="Lower stops sooner when the stepper meets resistance."
						for="threshold"
					>
						<Input id="threshold" type="number" bind:value={threshold} class="w-28" />
					</SettingRow>
				</div>
			</Disclosure>
		</div>
	</Panel>
{:else}
	<Panel>
		<EmptyState icon={Settings} title="Not part of this example">
			General and the stepper pages show how a settings page is built. The others follow the same
			layout.
		</EmptyState>
	</Panel>
{/if}
