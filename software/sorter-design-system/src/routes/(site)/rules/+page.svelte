<!--
	The rules, each with a wrong way and the right way side by side. The
	wrong ones break the rules on purpose (outlines, rounded corners, a
	spinning ring, raw hex): they are the only place those appear.
-->
<script lang="ts">
	import Info from '@lucide/svelte/icons/info';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Trash from '@lucide/svelte/icons/trash-2';
	import Copy from '@lucide/svelte/icons/copy';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Plus from '@lucide/svelte/icons/plus';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import DoDont from '$lib/site/DoDont.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import SettingRow from '$lib/components/SettingRow.svelte';
	import Input from '$lib/components/Input.svelte';
	import Button from '$lib/components/Button.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Switch from '$lib/components/Switch.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { rules } from '$lib/site/rules';

	const titles = Object.fromEntries(rules.map((r, i) => [r.id, `${i + 1}. ${r.title}`]));
	const leads = Object.fromEntries(rules.map((r) => [r.id, r.summary]));

	let selected = $state('c2');
	let decay = $state(true);
	let moveBy = $state<'duration' | 'degrees'>('degrees');
	let moveByOne = $state<'duration' | 'degrees'>('degrees');
</script>

<svelte:head><title>Rules · Sorter design system</title></svelte:head>

<PageHeader
	title="Rules"
	lead="The ten things that make the system hold together, each with the wrong way next to the right one. When a screen looks off, it is almost always one of these."
	doc="rules"
/>

<SiteSection title={titles['planes']} lead={leads['planes']}>
	<DoDont
		wrongNote="Every box outlined, every box the page's color. Nothing is in front of anything, so the eye has nowhere to land."
		rightNote="The panel stands off the page by its fill, and the chart is sunk into the panel. The fills do the separating; there is not a line in sight."
	>
		{#snippet wrong()}
			<div class="border border-line-strong p-4">
				<div class="text-sm font-semibold text-ink">Decay capture rate</div>
				<div class="mt-3 border border-line-strong p-3">
					<div class="text-sm text-ink-muted">burst 6/min, floor 1/hr over 3d</div>
					<div class="mt-2 h-10 border border-line-strong"></div>
				</div>
				<div class="mt-3 border border-line-strong p-3 text-sm text-ink">Burst rate</div>
			</div>
		{/snippet}
		{#snippet right()}
			<div class="bg-surface p-4">
				<div class="text-sm font-semibold text-ink">Decay capture rate</div>
				<div class="mt-3 bg-well p-3">
					<div class="text-sm text-ink-muted">burst 6/min, floor 1/hr over 3d</div>
					<div class="mt-2 h-10"></div>
				</div>
				<div class="mt-3 text-sm text-ink">Burst rate</div>
			</div>
		{/snippet}
	</DoDont>
	<DoDont
		wrongNote="A shadow under the card. It adds a second edge, soft and grey, that means nothing the fill does not already say."
		rightNote="The card stands off the page by its fill alone. Even what floats (a menu, a dialog) has a line and no shadow."
	>
		{#snippet wrong()}
			<div class="rounded-panel bg-surface p-4 shadow-lg">
				<div class="text-sm font-semibold text-ink">Standby</div>
				<p class="mt-1 text-sm text-ink-muted">Home starts the hardware.</p>
			</div>
		{/snippet}
		{#snippet right()}
			<div class="rounded-panel bg-surface p-4">
				<div class="text-sm font-semibold text-ink">Standby</div>
				<p class="mt-1 text-sm text-ink-muted">Home starts the hardware.</p>
			</div>
		{/snippet}
	</DoDont>
</SiteSection>

<SiteSection title={titles['double-lines']} lead={leads['double-lines']}>
	<DoDont
		wrongNote="A bordered row in a bordered panel: two lines at every edge, and two between rows, where the rows' own borders meet."
		rightNote="The panel has no border; the list draws one line between each pair of rows, and none above the first or below the last."
	>
		{#snippet wrong()}
			<div class="border border-line-strong bg-surface p-2">
				{#each ['Burst rate', 'Floor rate', 'Ramp'] as row (row)}
					<div class="flex items-center justify-between border border-line-strong px-3 py-2">
						<span class="text-sm text-ink">{row}</span>
						<span class="border border-line-strong px-2 py-0.5 text-sm text-ink">6</span>
					</div>
				{/each}
			</div>
		{/snippet}
		{#snippet right()}
			<div class="divide-y divide-line overflow-hidden rounded-panel bg-surface">
				{#each ['Burst rate', 'Floor rate', 'Ramp'] as row (row)}
					<div class="flex items-center justify-between px-4 py-2.5">
						<span class="text-sm text-ink">{row}</span>
						<Input type="number" value={6} size="sm" class="w-16" />
					</div>
				{/each}
			</div>
		{/snippet}
	</DoDont>
	<DoDont
		on="surface"
		wrongNote="Two bordered buttons pressed together share a seam, and the seam is two lines thick."
		rightNote="Buttons in a row keep a gap. Choices that belong together are one control, a segmented one: a single outline and one line between the segments."
	>
		{#snippet wrong()}
			<div class="flex">
				<span class="border border-line-strong px-3 py-1.5 text-sm text-ink">Duration</span>
				<span class="border border-line-strong px-3 py-1.5 text-sm text-ink">Degrees</span>
			</div>
		{/snippet}
		{#snippet right()}
			<div class="flex flex-wrap items-center gap-3">
				<SegmentedControl
					label="Move by"
					size="sm"
					bind:value={moveBy}
					options={[
						{ value: 'duration', label: 'Duration' },
						{ value: 'degrees', label: 'Degrees' }
					]}
				/>
				<Button size="sm">Cancel</Button>
				<Button size="sm" variant="primary">Save</Button>
			</div>
		{/snippet}
	</DoDont>
	<DoDont
		on="surface"
		wrongNote="A grey track with loose segments in it. With 1px corners and no shadows, the padding reads as a thick border around white boxes."
		rightNote="One control: a single outline, one 1px line between the segments, and the chosen one filled with the primary's tint. No track, no padding."
	>
		{#snippet wrong()}
			<div class="inline-flex gap-1 rounded-button bg-track p-1">
				<span class="rounded-button-inner bg-surface px-3 py-1.5 text-sm text-ink-muted"
					>Duration</span
				>
				<span class="rounded-button-inner bg-surface px-3 py-1.5 text-sm font-medium text-ink"
					>Degrees</span
				>
			</div>
		{/snippet}
		{#snippet right()}
			<SegmentedControl
				label="Move by, one control"
				bind:value={moveByOne}
				options={[
					{ value: 'duration', label: 'Duration' },
					{ value: 'degrees', label: 'Degrees' }
				]}
			/>
		{/snippet}
	</DoDont>
</SiteSection>

<SiteSection title={titles['spinner']} lead={leads['spinner']}>
	<DoDont
		on="surface"
		wrongNote="A ring spinning, a rounded dot pulsing: two indicators with two meanings, and neither of them ours."
		rightNote="The Spinner beside a sentence that says what is loading. In a button, it takes the icon's place and the label stays."
	>
		{#snippet wrong()}
			<div class="flex flex-col gap-3 text-sm text-ink-muted">
				<div class="flex items-center gap-2">
					<span
						class="size-4 animate-spin rounded-full border-2 border-ink-faint border-t-transparent"
					></span>
					Loading...
				</div>
				<div class="flex items-center gap-2">
					<span class="size-2.5 animate-pulse rounded-full bg-primary"></span>
					Please wait
				</div>
			</div>
		{/snippet}
		{#snippet right()}
			<div class="flex flex-col items-start gap-3">
				<div class="flex items-center gap-2 text-sm text-ink-muted">
					<Spinner size={16} />Checking the Hive connection
				</div>
				<Button variant="primary" loading>Saving</Button>
			</div>
		{/snippet}
	</DoDont>
</SiteSection>

<SiteSection title={titles['state']} lead={leads['state']}>
	<DoDont
		on="surface"
		wrongNote="The chosen row gets a thick colored border and the others a thin one: the list jumps as the line changes weight."
		rightNote="The chosen row takes the primary's tint, a hovered one a faint fill. Nothing moves; try it."
	>
		{#snippet wrong()}
			<div class="flex flex-col gap-1">
				{#each ['C-Channel 1', 'C-Channel 2', 'C-Channel 3'] as name, i (name)}
					<div
						class="px-3 py-1.5 text-sm text-ink {i === 1
							? 'border-2 border-primary'
							: 'border border-line-strong'}"
					>
						{name}
					</div>
				{/each}
			</div>
		{/snippet}
		{#snippet right()}
			<div class="flex flex-col gap-px">
				{#each [{ id: 'c1', name: 'C-Channel 1' }, { id: 'c2', name: 'C-Channel 2' }, { id: 'c3', name: 'C-Channel 3' }] as item (item.id)}
					<button
						type="button"
						onclick={() => (selected = item.id)}
						class="flex h-8 items-center px-3 text-left text-sm transition-colors {selected ===
						item.id
							? 'bg-primary-soft font-medium text-primary-ink'
							: 'text-ink-muted hover:bg-hover hover:text-ink'}"
					>
						{item.name}
					</button>
				{/each}
			</div>
		{/snippet}
	</DoDont>
</SiteSection>

<SiteSection title={titles['color']} lead={leads['color']}>
	<DoDont
		on="surface"
		wrongNote="A green save, a red heading that is not an error, a yellow box for emphasis. Each color has to be decoded, and none of them means what it says."
		rightNote="Structure is ink and grey. The one thing to do is the primary. Green appears once, and it means the machine is running."
	>
		{#snippet wrong()}
			<div class="flex flex-col gap-3">
				<div class="text-sm font-semibold text-danger-ink">Sorting profile</div>
				<div class="bg-warning-soft px-3 py-2 text-sm text-ink">Profile: September</div>
				<div>
					<span
						class="inline-flex h-9 items-center bg-success px-3.5 text-sm font-medium text-on-success"
						>Save</span
					>
				</div>
			</div>
		{/snippet}
		{#snippet right()}
			<div class="flex flex-col gap-3">
				<div class="flex items-center gap-2">
					<span class="text-sm font-semibold text-ink">Sorting profile</span>
					<Badge tone="success" dot>Running</Badge>
				</div>
				<div class="bg-well px-3 py-2 text-sm text-ink">Profile: September</div>
				<div><Button variant="primary">Save</Button></div>
			</div>
		{/snippet}
	</DoDont>
</SiteSection>

<SiteSection title={titles['corners']} lead={leads['corners']}>
	<DoDont
		on="surface"
		wrongNote="A rounded button, a square field, a pill of a badge and a softer card: four corners picked one at a time, and the screen looks assembled from different kits."
		rightNote="Panels, controls, buttons and badges each take their radius token: 1px, so they read as square and agree everywhere."
	>
		{#snippet wrong()}
			<div class="flex flex-col gap-3">
				<div class="flex flex-wrap items-center gap-3">
					<span
						class="inline-flex h-9 items-center rounded-lg bg-primary px-4 text-sm font-medium text-on-primary"
						>Home</span
					>
					<span
						class="inline-flex h-9 w-40 items-center border border-line-strong px-3 text-sm text-ink-faint"
						>Search parts</span
					>
					<span class="rounded-full bg-success-soft px-2.5 py-0.5 text-xs text-success-ink"
						>Idle</span
					>
				</div>
				<div class="rounded-2xl bg-well px-4 py-3 text-sm text-ink-muted">
					A card with its own idea.
				</div>
			</div>
		{/snippet}
		{#snippet right()}
			<div class="flex flex-col gap-3">
				<div class="flex flex-wrap items-center gap-3">
					<Button variant="primary">Home</Button>
					<Input placeholder="Search parts" class="w-40" />
					<Badge dot tone="success">Idle</Badge>
				</div>
				<div class="rounded-control bg-well px-4 py-3 text-sm text-ink-muted">
					A well, from the tokens.
				</div>
			</div>
		{/snippet}
	</DoDont>
</SiteSection>

<SiteSection title={titles['text']} lead={leads['text']}>
	<DoDont
		on="surface"
		wrongNote="Help text at 11px and 10px. Someone standing at the machine cannot read it, and it is the text that tells them what a setting does."
		rightNote="The setting's name and its sentence at 14px, and the section's name in sentence case beside them. Nothing is in capitals."
	>
		{#snippet wrong()}
			<div>
				<div class="text-[11px] font-semibold text-ink">Floor rate</div>
				<p class="mt-0.5 text-[10px] text-ink-muted">
					The fewest samples to save once the ramp has run out.
				</p>
			</div>
		{/snippet}
		{#snippet right()}
			<div>
				<div class="label mb-2">Sample capture</div>
				<div class="text-sm font-medium text-ink">Floor rate</div>
				<p class="mt-0.5 text-sm text-ink-muted">
					The fewest samples to save once the ramp has run out.
				</p>
			</div>
		{/snippet}
	</DoDont>
</SiteSection>

<SiteSection title={titles['tokens']} lead={leads['tokens']}>
	<DoDont
		on="surface"
		wrongNote="The card's colors are written as hex. Right on a light page; a white block on a dark one."
		rightNote="The card names tokens: bg-surface, text-ink. The same markup follows the page's mode, and is right in a dark one."
	>
		{#snippet wrong()}
			<div class="grid grid-cols-2 gap-2">
				<div class="bg-[#eceae5] p-3">
					<div class="bg-[#ffffff] p-3 text-sm text-[#1b1a18]">Burst rate</div>
				</div>
				<div class="bg-[#0e0e0d] p-3">
					<div class="bg-[#ffffff] p-3 text-sm text-[#1b1a18]">Burst rate</div>
				</div>
			</div>
		{/snippet}
		{#snippet right()}
			<div class="grid grid-cols-2 gap-2">
				<div class="bg-canvas p-3">
					<div class="bg-surface p-3 text-sm text-ink">Burst rate</div>
				</div>
				<div class="dark bg-canvas p-3">
					<div class="bg-surface p-3 text-sm text-ink">Burst rate</div>
				</div>
			</div>
		{/snippet}
	</DoDont>
</SiteSection>

<SiteSection title={titles['icons']} lead={leads['icons']}>
	<DoDont
		on="surface"
		wrongNote="Four bare icons. Which one deletes? A hand-drawn path next to Lucide's also sits at a different weight."
		rightNote="Words carry the action and the icon backs them up. An icon button has a name, shown when you point at it."
	>
		{#snippet wrong()}
			<div class="flex items-center gap-4 text-ink-muted">
				<Pencil size={18} />
				<Copy size={18} />
				<Trash size={18} />
				<svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true"
					><path d="M3 9a6 6 0 1 0 2-4.5M3 3v3h3" stroke="currentColor" stroke-width="2.5" /></svg
				>
			</div>
		{/snippet}
		{#snippet right()}
			<div class="flex flex-wrap items-center gap-2">
				<Button size="sm" icon={Plus}>Add bin</Button>
				<Button size="sm" variant="ghost" icon={RefreshCw}>Rescan</Button>
				<Button size="sm" variant="ghost" icon={Trash} label="Delete profile" />
			</div>
		{/snippet}
	</DoDont>
</SiteSection>

<SiteSection title={titles['copy']} lead={leads['copy']}>
	<Specimen
		code={`// In the Sorter UI or Hive: the file copied from
// software/sorter-design-system/src/lib/components/Button.svelte, unchanged.
import Button from '$lib/components/Button.svelte';

<Button variant="primary" icon={Home}>Home</Button>

// Not this: a raw button restyled inline drifts from every other button.
<button class="bg-blue-600 px-4 py-2 text-white">Home</button>`}
	>
		<div class="flex items-start gap-3 text-sm text-ink-muted">
			<Info size={18} class="mt-px shrink-0 text-info-ink" />
			<p class="max-w-2xl">
				A component that needs something new (a variant, a size) gets it here first, with its
				example on the right page, and the app copies the file again. So there is one Button, not
				one per screen.
			</p>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="In one panel"
	lead="All of it at once: a panel on the canvas, rows divided once, a well for the chart, a switch, fields with units, one primary."
>
	<div>
		<Panel
			title="Decay capture rate"
			description="Save many samples at first, then fewer as the machine sees more."
			flush
		>
			<div class="divide-y divide-line">
				<SettingRow label="Decay the rate" help="Off keeps the burst rate forever.">
					<Switch bind:checked={decay} label="Decay the rate" />
				</SettingRow>
				<SettingRow label="Burst rate" help="Samples a minute at the start." for="rules-burst">
					<Input id="rules-burst" type="number" value={6} unit="/min" class="w-28" />
				</SettingRow>
			</div>
			{#snippet footer()}
				<Button variant="primary">Save</Button>
			{/snippet}
		</Panel>
	</div>
</SiteSection>
