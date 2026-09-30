<!--
	Settings > General, rebuilt: the same settings as the Sorter UI's page,
	laid out by the rules. One panel per job, rows divided once, sub-settings
	in a well under the setting they belong to, one primary per panel at most.
-->
<script lang="ts">
	import Plug from '@lucide/svelte/icons/plug';
	import Sun from '@lucide/svelte/icons/sun';
	import Moon from '@lucide/svelte/icons/moon';
	import HardDrive from '@lucide/svelte/icons/hard-drive';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Panel from '$lib/components/Panel.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import SettingRow from '$lib/components/SettingRow.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Button from '$lib/components/Button.svelte';
	import Switch from '$lib/components/Switch.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import ColorPicker from '$lib/components/ColorPicker.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { theme, type Mode } from '$lib/theme.svelte';

	let address = $state('ws://sorter.local:8000/ws');
	let connecting = $state(false);
	let name = $state('Bench sorter');
	let savedName = $state('Bench sorter');
	let mode = $state<Mode>(theme.mode);
	let colorId = $state(theme.colorId);

	let decay = $state(true);
	let rates = $state({ burst: 6, floor: 1, ramp: 3, jitter: 30 });
	const defaultCap = 1;
	let cap = $state(4);

	const rateRows = [
		{ id: 'burst', label: 'Burst rate', help: 'Samples a minute at the start.', unit: '/min' },
		{
			id: 'floor',
			label: 'Floor rate',
			help: 'The fewest samples once the ramp has run out.',
			unit: '/hr'
		},
		{
			id: 'ramp',
			label: 'Ramp',
			help: 'How long the rate takes to fall to the floor.',
			unit: 'days'
		},
		{ id: 'jitter', label: 'Jitter', help: 'Randomness in when a sample is taken.', unit: '%' }
	] as const;

	function connect() {
		connecting = true;
		setTimeout(() => (connecting = false), 1200);
	}

	// The decay curve, drawn in a 100 x 40 box: from the burst rate down to
	// the floor over the ramp, on a log scale so the floor is visible.
	const curve = $derived.by(() => {
		const perMinuteFloor = rates.floor / 60;
		const top = Math.log(Math.max(rates.burst, 0.01));
		const bottom = Math.log(Math.max(perMinuteFloor, 0.001));
		const span = top - bottom || 1;
		const points: string[] = [];
		for (let i = 0; i <= 40; i++) {
			const t = i / 40;
			const rate = Math.exp(top - (top - bottom) * t);
			const y = 4 + (1 - (Math.log(rate) - bottom) / span) * 32;
			points.push(`${(t * 100).toFixed(1)},${y.toFixed(1)}`);
		}
		return points.join(' ');
	});
</script>

<svelte:head><title>General · Settings · Example app</title></svelte:head>

{#snippet decayDetail()}
	<div class="flex items-center justify-between gap-3 px-4 pt-3">
		<p class="text-sm text-ink-muted tabular-nums">
			<span class="font-medium text-ink">{rates.burst}/min</span>, falling to
			<span class="font-medium text-ink">{rates.floor}/hr</span> over
			<span class="font-medium text-ink">{rates.ramp} days</span>. Now
			<span class="font-medium text-ink">{rates.burst.toFixed(2)}/min</span>.
		</p>
		<Button size="sm" variant="ghost">Reset decay</Button>
	</div>
	<svg
		viewBox="0 0 100 40"
		preserveAspectRatio="none"
		class="block h-24 w-full px-4 py-2"
		role="img"
		aria-label="Capture rate falling from the burst rate to the floor rate over the ramp"
	>
		<polyline
			points={curve}
			fill="none"
			stroke="var(--primary)"
			stroke-width="1.5"
			vector-effect="non-scaling-stroke"
		/>
	</svg>
	<div class="divide-y divide-line">
		{#each rateRows as row (row.id)}
			<div class="flex items-center justify-between gap-6 px-4 py-2.5">
				<div class="min-w-0">
					<label for="decay-{row.id}" class="text-sm font-medium text-ink">{row.label}</label>
					<p class="text-sm text-ink-muted">{row.help}</p>
				</div>
				<Input
					id="decay-{row.id}"
					type="number"
					bind:value={rates[row.id]}
					unit={row.unit}
					class="w-28 shrink-0"
				/>
			</div>
		{/each}
	</div>
{/snippet}

<PageHeader
	title="General"
	description="This machine, how this page reaches it, and how it looks."
/>

<Panel title="Connection" description="The machine this page is talking to." flush>
	<div class="divide-y divide-line">
		<div class="px-5 pb-4">
			<Field label="Address" for="address" help="The machine's backend, as ws://host:8000/ws.">
				<div class="flex gap-2">
					<Input id="address" type="url" bind:value={address} class="min-w-0 flex-1 font-mono" />
					<Button icon={Plug} loading={connecting} onclick={connect}>Connect</Button>
				</div>
			</Field>
		</div>
		<div class="px-5 py-4">
			<div class="label">Connected machines</div>
			<ul class="mt-2 divide-y divide-line">
				<li class="flex items-center gap-3 py-2">
					<span class="size-2 shrink-0 rounded-full bg-success" aria-hidden="true"></span>
					<div class="min-w-0 flex-1">
						<div class="truncate text-sm font-medium text-ink">{savedName}</div>
						<div class="truncate font-mono text-sm text-ink-muted">{address}</div>
					</div>
					<Button size="sm" variant="ghost">Disconnect</Button>
				</li>
			</ul>
		</div>
	</div>
</Panel>

<Panel title="Machine" flush>
	<div class="px-5 pb-5">
		<Field label="Name" for="machine-name" help="Leave it blank to use the machine's ID.">
			<div class="flex gap-2">
				<Input id="machine-name" bind:value={name} class="min-w-0 flex-1" />
				<Button disabled={name === savedName} onclick={() => (savedName = name)}>Save name</Button>
			</div>
		</Field>
	</div>
</Panel>

<Panel title="Appearance" flush>
	<div class="divide-y divide-line">
		<SettingRow label="Theme" help="Applies at once, on this browser.">
			<SegmentedControl
				label="Theme"
				bind:value={mode}
				onchange={(m) => theme.setMode(m)}
				options={[
					{ value: 'light', label: 'Light', icon: Sun },
					{ value: 'dark', label: 'Dark', icon: Moon }
				]}
			/>
		</SettingRow>
		<div class="px-5 py-3.5">
			<div class="text-sm font-medium text-ink">Theme color</div>
			<p class="mt-0.5 text-sm text-ink-muted">
				The LEGO color of buttons, focus rings and the current page. Applies at once.
			</p>
			<div class="mt-3 bg-well p-4">
				<ColorPicker bind:value={colorId} onchange={(id) => theme.setColor(id)} />
			</div>
		</div>
		<SettingRow
			label="Setup wizard"
			help="Walk through the hardware, the cameras and the first configuration again."
		>
			<Button icon={ArrowRight}>Open setup wizard</Button>
		</SettingRow>
	</div>
</Panel>

<Panel
	title="Sample capture"
	description="Photos of classified parts, kept on this machine for training."
	flush
>
	<div class="divide-y divide-line">
		<SettingRow
			label="Decay the capture rate"
			help="Save many samples at first, then fewer as the machine has seen more."
			below={decay ? decayDetail : undefined}
		>
			<Switch bind:checked={decay} label="Decay the capture rate" />
		</SettingRow>
		<SettingRow
			label="Local storage cap"
			help="Past this, the oldest samples are deleted. Using 0.00 GB."
			for="storage-cap"
			changed={cap !== defaultCap}
			defaultText="{defaultCap} GB"
			onreset={() => (cap = defaultCap)}
		>
			<Input id="storage-cap" type="number" bind:value={cap} unit="GB" class="w-28" />
		</SettingRow>
		<SettingRow label="Saved this session">
			<span class="num text-sm text-ink">0</span>
		</SettingRow>
	</div>
</Panel>

<Panel title="Local samples" description="Sample sessions stored on this machine.">
	<EmptyState icon={HardDrive} title="No sample sessions on disk">
		Sessions appear here as the machine saves samples.
	</EmptyState>
</Panel>
