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
	import Badge from '$lib/components/Badge.svelte';
	import SettingRow from '$lib/components/SettingRow.svelte';
	import Step from '$lib/components/Step.svelte';
	import Button from '$lib/components/Button.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import CopyField from '$lib/components/CopyField.svelte';

	let name = $state('Bench sorter');
	let port = $state<number | null>(80000);
	let camera = $state('usb-2');
	let note = $state('');
	let since = $state('2026-10-01');
	let wifiPassword = $state('');
	let showPassword = $state(false);
	let upload = $state(true);
	let keepRaw = $state(false);
	let mode = $state<'color' | 'part' | 'set'>('part');
	let capture = $state(true);
	let theme = $state<'light' | 'dark'>('light');
	let threshold = $state(40);
	let saved = $state(40);
	let saving = $state(false);
	let justSaved = $state(false);
	const defaults = { burst: 6, floor: 1, jitter: 30 };
	let rates = $state({ burst: 9, floor: 1, jitter: 45 });
	const sharedDefaults = { records: true, pictures: true, frames: true };
	let shared = $state({ records: true, pictures: false, frames: true });
	let stuck = $state<'off' | 'manual' | 'automatic'>('manual');
	// The step to do in the Steps specimen: the ones before it are done, the ones after it locked.
	let stepAt = $state(2);
	const stepStatus = (n: number) => (n < stepAt ? 'done' : n === stepAt ? 'current' : 'locked');

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
	lead="Fields, choices and switches, the two ways a setting is saved (at once, or with a Save), and the steps of a task done once."
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
			<Field
				label="Speed"
				for="f-speed"
				info="Steps a second at the motor. Faster feeds more pieces, and past the motor's limit it skips steps."
			>
				<Input id="f-speed" type="number" value={800} unit="steps/s" />
			</Field>
			<Field
				label="Wi-Fi password"
				for="f-password"
				help="A small control can sit inside the edge."
			>
				<Input
					id="f-password"
					type={showPassword ? 'text' : 'password'}
					bind:value={wifiPassword}
					autocomplete="off"
				>
					{#snippet end()}
						<Button size="sm" variant="ghost" onclick={() => (showPassword = !showPassword)}>
							{showPassword ? 'Hide' : 'Show'}
						</Button>
					{/snippet}
				</Input>
			</Field>
			<Field label="Seen since" for="f-since" help="A day, picked with the browser's own calendar.">
				<Input id="f-since" type="date" bind:value={since} />
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
	title="Something to copy"
	lead="The text whole, in a well, with one Copy button at its edge. A secret shown once says so in a quiet sentence under it, not in a warning."
>
	<Specimen
		code={`<CopyField label="API key" value={token} mono note="Shown only now. Copy it before you leave the page." />`}
	>
		<div class="flex max-w-2xl flex-col gap-6">
			<CopyField
				label="API key"
				value="hv_example4TmK2x9Qp0Lr7Zs1Nw8Vb3"
				mono
				note="Shown only now. Copy it before you leave the page."
			/>
			<CopyField
				label="Paste this into your assistant"
				name="message"
				value="Use the Hive sorting-profiles skill at https://hive.example.com/api/agent/skill.md. My API key is hv_example4TmK2x9Qp0Lr7Zs1Nw8Vb3."
				note="The message holds the key, so it has the one button."
			>
				Use the Hive sorting-profiles skill at
				<span class="font-mono">https://hive.example.com/api/agent/skill.md</span>. My API key is
				<span class="font-mono">hv_example4TmK2x9Qp0Lr7Zs1Nw8Vb3</span>.
			</CopyField>
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
	title="A dense list of settings"
	lead="Where a sentence under every row would make the list as tall as a page, a row keeps its explanation behind an info icon after its name. Pointing at the icon, or tabbing to it, shows the text, and the row stays one line. A warning a person must see is still written under the setting."
>
	<Specimen
		on="canvas"
		code={`<SettingRow label="Piece pictures" changed={!shared.pictures}
	info="The photo of each piece, used to train recognition. The largest thing a sorter sends."
	defaultText="on" onreset={() => (shared.pictures = true)}>
	<Switch bind:checked={shared.pictures} label="Piece pictures" />
</SettingRow>`}
	>
		<Panel title="Shared with Hive" flush>
			<div class="divide-y divide-line">
				<SettingRow
					label="Machine status"
					info="The software version and how much this machine has sorted, once an hour. Always on."
				>
					<Badge>Always</Badge>
				</SettingRow>
				<SettingRow
					label="Piece records"
					info="One line per piece: its part, its color and when it was sorted. No pictures."
					changed={shared.records !== sharedDefaults.records}
					defaultText="on"
					onreset={() => (shared.records = sharedDefaults.records)}
				>
					<Switch bind:checked={shared.records} label="Piece records" />
				</SettingRow>
				<SettingRow
					label="Piece pictures"
					info="The photo of each piece, used to train recognition. The largest thing a sorter sends."
					changed={shared.pictures !== sharedDefaults.pictures}
					defaultText="on"
					onreset={() => (shared.pictures = sharedDefaults.pictures)}
				>
					<Switch bind:checked={shared.pictures} label="Piece pictures" />
				</SettingRow>
				<SettingRow
					label="Camera frames"
					info="A whole frame from each camera now and then, to teach the detectors what the machine sees."
					changed={shared.frames !== sharedDefaults.frames}
					defaultText="on"
					onreset={() => (shared.frames = sharedDefaults.frames)}
				>
					<Switch bind:checked={shared.frames} label="Camera frames" />
				</SettingRow>
			</div>
		</Panel>
	</Specimen>
</SiteSection>

<SiteSection
	title="A setting changed from its default"
	lead="A row whose value is not the default takes the primary's tint, and one button beside its name puts the default back. The button sits on the name's line, so the row does not jump as the value changes, and pointing at it says what the default is."
>
	<Specimen
		on="canvas"
		code={`<SettingRow label="Burst rate" for="burst" changed={burst !== 6}
	defaultText="6 /min" onreset={() => (burst = 6)}>
	<Input id="burst" type="number" bind:value={burst} unit="/min" class="w-28" />
</SettingRow>`}
	>
		<Panel title="Sample capture" flush>
			<div class="divide-y divide-line">
				<SettingRow
					label="Burst rate"
					help="Samples a minute at the start."
					for="f-burst"
					changed={rates.burst !== defaults.burst}
					defaultText="{defaults.burst} /min"
					onreset={() => (rates.burst = defaults.burst)}
				>
					<Input id="f-burst" type="number" bind:value={rates.burst} unit="/min" class="w-28" />
				</SettingRow>
				<SettingRow
					label="Floor rate"
					help="The fewest samples once the ramp has run out."
					for="f-floor"
					changed={rates.floor !== defaults.floor}
					defaultText="{defaults.floor} /hr"
					onreset={() => (rates.floor = defaults.floor)}
				>
					<Input id="f-floor" type="number" bind:value={rates.floor} unit="/hr" class="w-28" />
				</SettingRow>
				<SettingRow
					label="Jitter"
					help="Randomness in when a sample is taken."
					for="f-jitter"
					changed={rates.jitter !== defaults.jitter}
					defaultText="{defaults.jitter}%"
					onreset={() => (rates.jitter = defaults.jitter)}
				>
					<Input id="f-jitter" type="number" bind:value={rates.jitter} unit="%" class="w-28" />
				</SettingRow>
				<SettingRow
					label="Stuck on the classification channel"
					help="The channel stopped making progress with a piece on it."
					changed={stuck !== 'automatic'}
					defaultText="Automatic"
					defaultHelp="Automatic: turn the channel forward until it clears."
					onreset={() => (stuck = 'automatic')}
				>
					{#snippet tags()}<Badge>Classification</Badge>{/snippet}
					<SegmentedControl
						label="When a piece is stuck"
						size="sm"
						bind:value={stuck}
						options={[
							{ value: 'off', label: 'Off' },
							{ value: 'manual', label: 'Manual' },
							{ value: 'automatic', label: 'Automatic' }
						]}
					/>
				</SettingRow>
			</div>
		</Panel>
	</Specimen>
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

<SiteSection
	title="Steps"
	lead="A task done once and not by heart, in order. The step to do is open, a done step is one line with its result, and a locked step says what to finish first. The page decides which is which from what it knows, so it is right after a reload."
>
	<Specimen
		on="canvas"
		code={`<Panel title="Tune a motor" flush>
	{#snippet actions()}<Badge tone="primary">Step 2 of 4</Badge>{/snippet}
	<ol class="divide-y divide-line border-t border-line">
		<Step n={1} title="Check the speed" status="done" hint="1,500 steps/s at 1/8 microstepping">
			{#snippet actions()}<Button variant="ghost" size="sm">Change</Button>{/snippet}
		</Step>
		<Step n={2} title="Record it running freely" status="current">
			...what it does and why, then <Button variant="primary">Record it running freely</Button>
		</Step>
		<Step n={3} title="Record a stall" status="locked" hint="Record it running freely first." />
	</ol>
</Panel>`}
	>
		<Panel
			title="Tune a motor"
			description="Four steps, in order. Nothing is saved until the last."
			flush
		>
			{#snippet actions()}
				{#if stepAt > 4}
					<Badge tone="success">Tuned</Badge>
				{:else}
					<Badge tone="primary">Step {stepAt} of 4</Badge>
				{/if}
			{/snippet}
			<ol class="divide-y divide-line border-t border-line">
				<Step
					n={1}
					title="Check the speed"
					status={stepStatus(1)}
					hint={stepStatus(1) === 'done' ? '1,500 steps/s at 1/8 microstepping' : undefined}
				>
					{#snippet actions()}
						{#if stepStatus(1) === 'done'}
							<Button variant="ghost" size="sm" onclick={() => (stepAt = 1)}>Change</Button>
						{/if}
					{/snippet}
					<div class="flex flex-col gap-3">
						<p class="text-sm text-ink">
							The load reading changes with speed, so the motor is tuned at the speed it really runs
							at.
						</p>
						<div>
							<Button variant="primary" onclick={() => (stepAt = 2)}>Tune at 1,500 steps/s</Button>
						</div>
					</div>
				</Step>
				<Step
					n={2}
					title="Record it running freely"
					status={stepStatus(2)}
					hint={stepStatus(2) === 'done'
						? 'Running freely it reads 168 or higher.'
						: stepStatus(2) === 'locked'
							? 'Check the speed first.'
							: undefined}
				>
					{#snippet actions()}
						{#if stepStatus(2) === 'done'}
							<Button variant="ghost" size="sm" onclick={() => (stepAt = 2)}>Record again</Button>
						{/if}
					{/snippet}
					<div class="flex flex-col gap-3">
						<p class="text-sm text-ink">
							The motor runs a short move with nothing holding it back. This is what normal running
							reads, and a stall has to read well below it.
						</p>
						<Alert tone="warning">This moves a real motor. Keep the area clear.</Alert>
						<div>
							<Button variant="primary" onclick={() => (stepAt = 3)}
								>Record it running freely</Button
							>
						</div>
					</div>
				</Step>
				<Step
					n={3}
					title="Record a stall"
					status={stepStatus(3)}
					hint={stepStatus(3) === 'done'
						? 'Held back, it dips to 12.'
						: stepStatus(3) === 'locked'
							? 'Record it running freely first.'
							: undefined}
				>
					{#snippet actions()}
						{#if stepStatus(3) === 'done'}
							<Button variant="ghost" size="sm" onclick={() => (stepAt = 3)}>Record again</Button>
						{/if}
					{/snippet}
					<div class="flex flex-col gap-3">
						<p class="text-sm text-ink">
							The same move again, held back by hand, so it stalls. This shows what a stall reads.
						</p>
						<div>
							<Button variant="primary" onclick={() => (stepAt = 4)}>Record a stall</Button>
						</div>
					</div>
				</Step>
				<Step
					n={4}
					title="Review and save"
					status={stepStatus(4)}
					hint={stepStatus(4) === 'done'
						? 'Saved: threshold 38, speed floor 438.'
						: stepStatus(4) === 'locked'
							? 'Needs both recordings.'
							: undefined}
				>
					{#snippet actions()}
						{#if stepStatus(4) === 'done'}
							<Button variant="ghost" size="sm" onclick={() => (stepAt = 4)}>Review</Button>
						{/if}
					{/snippet}
					<div class="flex flex-col gap-3">
						<p class="text-sm text-ink">
							A stall reads 12 or lower and running freely 168 or higher. The trigger sits between
							at 76.
						</p>
						<div>
							<Button variant="primary" onclick={() => (stepAt = 5)}>Save these settings</Button>
						</div>
					</div>
				</Step>
			</ol>
		</Panel>
	</Specimen>
	<div>
		<Button variant="ghost" onclick={() => (stepAt = 1)}>Start over</Button>
	</div>
</SiteSection>
