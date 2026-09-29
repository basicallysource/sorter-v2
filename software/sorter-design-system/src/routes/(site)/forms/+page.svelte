<script lang="ts">
	import Sun from '@lucide/svelte/icons/sun';
	import Moon from '@lucide/svelte/icons/moon';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import Checkbox from '$lib/components/Checkbox.svelte';
	import RadioGroup from '$lib/components/RadioGroup.svelte';
	import Switch from '$lib/components/Switch.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import SettingRow from '$lib/components/SettingRow.svelte';
	import Button from '$lib/components/Button.svelte';
	import Alert from '$lib/components/Alert.svelte';

	let name = $state('Bench sorter');
	let port = $state<number | null>(80000);
	let camera = $state('usb-2');
	let note = $state('');
	let upload = $state(true);
	let keepRaw = $state(false);
	let mode = $state<'color' | 'part' | 'set'>('part');
	let capture = $state(true);
	let theme = $state<'light' | 'dark'>('light');
	let threshold = $state(40);
	let saved = $state(40);
	let saving = $state(false);
	let justSaved = $state(false);

	const portError = $derived(
		port === null || port < 1 || port > 65535 ? 'A port is a number from 1 to 65535.' : undefined
	);

	function save() {
		saving = true;
		setTimeout(() => {
			saving = false;
			saved = threshold;
			justSaved = true;
			setTimeout(() => (justSaved = false), 2500);
		}, 900);
	}
</script>

<svelte:head><title>Forms · Sorter design system</title></svelte:head>

<PageHeader
	title="Forms"
	lead="Fields, choices and switches, and the two ways a setting is saved: at once, or with a Save."
	doc="components"
/>

<SiteSection
	title="Fields"
	lead="A label over the field, one sentence under it: help, or the error in its place. A unit sits inside the field's edge."
>
	<Specimen
		code={`<Field label="Port" for="port" error={portError}>
	<Input id="port" type="number" bind:value={port} invalid={!!portError} />
</Field>`}
	>
		<div class="grid max-w-2xl gap-5 sm:grid-cols-2">
			<Field label="Machine name" for="f-name" help="Leave it blank to use the machine's ID.">
				<Input id="f-name" bind:value={name} />
			</Field>
			<Field label="Port" for="f-port" error={portError}>
				<Input id="f-port" type="number" bind:value={port} invalid={!!portError} />
			</Field>
			<Field label="Camera" for="f-camera">
				<Select
					id="f-camera"
					bind:value={camera}
					options={[
						{ value: 'usb-1', label: 'USB camera 1 (1920 x 1080)' },
						{ value: 'usb-2', label: 'USB camera 2 (1280 x 720)' },
						{ value: 'none', label: 'No camera' }
					]}
				/>
			</Field>
			<Field label="Speed" for="f-speed" help="Steps a second at the motor.">
				<Input id="f-speed" type="number" value={800} unit="steps/s" />
			</Field>
			<Field label="Note" for="f-note" class="sm:col-span-2">
				<Textarea
					id="f-note"
					bind:value={note}
					rows={3}
					placeholder="What changed on the machine"
				/>
			</Field>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="Choices"
	lead="A checkbox for a choice saved with a form; radios when each choice needs a sentence; a segmented control for two to five short choices that apply at once; a select for more."
>
	<div class="grid gap-4 md:grid-cols-2">
		<Specimen>
			<div class="flex flex-col gap-3">
				<Checkbox bind:checked={upload}>Upload samples to Hive</Checkbox>
				<Checkbox bind:checked={keepRaw}>Keep the raw photos too</Checkbox>
				<Checkbox disabled>Share with other machines</Checkbox>
			</div>
		</Specimen>
		<Specimen>
			<RadioGroup
				name="sort-by"
				label="Sort by"
				bind:value={mode}
				options={[
					{ value: 'color', label: 'Color', help: 'Every part of one color goes to one bin.' },
					{ value: 'part', label: 'Part', help: 'Every copy of one part goes to one bin.' },
					{ value: 'set', label: 'Set', help: 'Parts go where a set needs them.' }
				]}
			/>
		</Specimen>
	</div>
	<Specimen>
		<div class="flex flex-wrap items-center gap-6">
			<SegmentedControl
				label="Theme"
				bind:value={theme}
				options={[
					{ value: 'light', label: 'Light', icon: Sun },
					{ value: 'dark', label: 'Dark', icon: Moon }
				]}
			/>
			<div class="flex items-center gap-3">
				<Switch bind:checked={capture} label="Capture samples" />
				<span class="text-sm text-ink">Capture samples</span>
			</div>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="Settings that apply at once"
	lead="A switch or a segmented control changes the machine the moment it moves, so it needs no Save. Rows sit in a divided list in a flush panel."
>
	<Panel title="Sample capture" flush>
		<div class="divide-y divide-line">
			<SettingRow label="Capture samples" help="Save a photo of each part as it is classified.">
				<Switch bind:checked={capture} label="Capture samples" />
			</SettingRow>
			<SettingRow label="Theme" help="Applies at once, on this browser.">
				<SegmentedControl
					label="Theme"
					size="sm"
					bind:value={theme}
					options={[
						{ value: 'light', label: 'Light' },
						{ value: 'dark', label: 'Dark' }
					]}
				/>
			</SettingRow>
		</div>
	</Panel>
</SiteSection>

<SiteSection
	title="Settings saved together"
	lead="Fields that belong together save with one primary button in the panel's footer, next to the way back. While it saves the button shows the Spinner; after, a sentence says so. Nothing pops up."
>
	<Panel title="StallGuard" description="Stops the stepper when it meets resistance." flush>
		<div class="divide-y divide-line">
			<SettingRow label="Threshold" help="Lower stops sooner." for="f-threshold">
				<Input id="f-threshold" type="number" bind:value={threshold} class="w-28" />
			</SettingRow>
		</div>
		{#snippet footer()}
			{#if justSaved}<span class="mr-auto text-sm text-success-ink">Saved.</span>{/if}
			<Button variant="ghost" disabled={threshold === saved} onclick={() => (threshold = saved)}
				>Reset</Button
			>
			<Button variant="primary" loading={saving} disabled={threshold === saved} onclick={save}
				>Save</Button
			>
		{/snippet}
	</Panel>
	<Alert tone="info">
		A save that fails keeps the values as they were typed and puts an Alert above the footer saying
		what went wrong.
	</Alert>
</SiteSection>
