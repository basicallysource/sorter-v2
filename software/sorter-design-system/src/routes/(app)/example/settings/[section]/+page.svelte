<!--
	The other settings pages. A channel with a camera shows the camera as the
	main thing, with its stepper's controls beside it; a stepper without one
	shows the controls alone. The rest are outside this example.
-->
<script lang="ts">
	import Camera from '@lucide/svelte/icons/camera';
	import RotateCw from '@lucide/svelte/icons/rotate-cw';
	import Settings from '@lucide/svelte/icons/settings';
	import { page } from '$app/state';
	import Panel from '$lib/components/Panel.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import MediaTile from '$lib/components/MediaTile.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import SettingRow from '$lib/components/SettingRow.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import JogControl from '../JogControl.svelte';
	import { cameraSections, labelFor } from '../nav';

	const steppers = ['c-channel-1', 'chute', ...cameraSections];
	const section = $derived(page.params.section ?? '');
	const title = $derived(labelFor(section) ?? 'Settings');

	const defaults = { current: 900, microsteps: '16', threshold: 40 };
	let current = $state(defaults.current);
	let microsteps = $state(defaults.microsteps);
	let threshold = $state(32);
</script>

<svelte:head><title>{title} · Settings · Example app</title></svelte:head>

{#snippet stepper()}
	<Panel flush>
		<div class="flex items-center justify-between gap-3 px-(--pad-panel) pt-4 pb-3">
			<span class="text-base font-semibold text-ink">Stepper</span>
			<Badge dot>Idle</Badge>
		</div>
		<div class="px-(--pad-panel) pb-(--pad-panel)">
			<JogControl />
		</div>
		<div class="border-t border-line">
			<Disclosure title="Driver settings">
				<div class="divide-y divide-line pl-6">
					<SettingRow
						label="Run current"
						help="Higher holds better and runs hotter."
						for="current"
						changed={current !== defaults.current}
						defaultText="{defaults.current} mA"
						onreset={() => (current = defaults.current)}
					>
						<Input id="current" type="number" bind:value={current} unit="mA" class="w-28" />
					</SettingRow>
					<SettingRow
						label="Microsteps"
						for="microsteps"
						changed={microsteps !== defaults.microsteps}
						defaultText={defaults.microsteps}
						onreset={() => (microsteps = defaults.microsteps)}
					>
						<Select
							id="microsteps"
							class="w-28"
							bind:value={microsteps}
							options={['8', '16', '32', '64'].map((m) => ({ value: m, label: m }))}
						/>
					</SettingRow>
					<SettingRow
						label="StallGuard threshold"
						help="Lower stops sooner when the stepper meets resistance."
						for="threshold"
						changed={threshold !== defaults.threshold}
						defaultText={String(defaults.threshold)}
						onreset={() => (threshold = defaults.threshold)}
					>
						<Input id="threshold" type="number" bind:value={threshold} class="w-28" />
					</SettingRow>
				</div>
			</Disclosure>
		</div>
	</Panel>
{/snippet}

<PageHeader
	{title}
	description={cameraSections.includes(section)
		? "What this channel's camera sees, and its stepper."
		: steppers.includes(section)
			? 'Move the stepper by hand, and set its driver.'
			: undefined}
/>

{#if cameraSections.includes(section)}
	<div class="grid items-start gap-(--gap-panels) xl:grid-cols-[minmax(0,1fr)_23rem]">
		<MediaTile title="{title} camera" expandable>
			{#snippet actions()}
				<Button size="sm" variant="ghost">-1°</Button>
				<Button size="sm" variant="ghost">+1°</Button>
				<Button size="sm" variant="ghost" icon={RotateCw}>180°</Button>
			{/snippet}
			{#snippet overlay()}
				<Badge tone="success" dot>Live</Badge>
			{/snippet}
			<Camera size={24} class="text-ink-faint" />
		</MediaTile>
		<div class="max-w-xl xl:max-w-none">{@render stepper()}</div>
	</div>
{:else if steppers.includes(section)}
	<div class="max-w-xl">{@render stepper()}</div>
{:else}
	<Panel>
		<EmptyState icon={Settings} title="Not part of this example">
			General and the channel pages show how a settings page is built. The others follow the same
			layout.
		</EmptyState>
	</Panel>
{/if}
