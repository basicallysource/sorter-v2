<script lang="ts">
	import RotateCw from '@lucide/svelte/icons/rotate-cw';
	import Cpu from '@lucide/svelte/icons/cpu';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import DoDont from '$lib/site/DoDont.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import Tabs from '$lib/components/Tabs.svelte';
	import Popover from '$lib/components/Popover.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Card from '$lib/components/Card.svelte';
	import MediaTile from '$lib/components/MediaTile.svelte';

	const planes = [
		{
			name: 'Canvas',
			token: 'bg-canvas',
			fill: 'bg-canvas',
			holds: 'The page itself: page titles and the gaps between panels.'
		},
		{
			name: 'Surface',
			token: 'bg-surface',
			fill: 'bg-surface',
			holds:
				"A panel, the top bar, the side nav: one job's worth of content each. No border, no shadow."
		},
		{
			name: 'Well',
			token: 'bg-well',
			fill: 'bg-well',
			holds: 'Sunk into a panel: a chart, a preview, an empty list. A box with the panel around it, never a band across it.'
		},
		{
			name: 'Raised',
			token: 'bg-raised',
			fill: 'bg-raised',
			holds:
				'Floats over everything: popovers, menus, tooltips, dialogs. A fill and one line; no shadow.'
		},
		{
			name: 'Media',
			token: 'bg-media',
			fill: 'bg-media',
			holds:
				'Behind camera feeds and photos. Dark in both modes, so a picture never sits in a white box.'
		}
	];

	let tab = $state<'live' | 'recent' | 'errors'>('live');
	let unit = $state<'duration' | 'degrees'>('degrees');
	let chosen = $state(2);

	const machines = [
		{ id: 'bench', name: 'Bench sorter', where: 'Garage, second shelf', online: true, today: 1284 },
		{ id: 'shop', name: 'Shop sorter', where: 'Back room', online: false, today: 0 }
	];

	// A stand-in for a camera's picture: an image of its own shape, so the tile shows how it hugs one.
	function sampleFeed(width: number, height: number) {
		const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" fill="#565c66"/><circle cx="${width / 2}" cy="${height / 2}" r="${height * 0.34}" fill="#8b93a1"/><circle cx="${width / 2}" cy="${height / 2}" r="${height * 0.08}" fill="#2b2f36"/></svg>`;
		return `data:image/svg+xml,${encodeURIComponent(svg)}`;
	}
</script>

<svelte:head><title>Surfaces · Sorter design system</title></svelte:head>

<PageHeader
	title="Surfaces"
	lead="The planes a screen is built from, the two kinds of line, and which part owns each line. Together they let a screen separate its parts without outlining them."
	doc="surfaces"
/>

<SiteSection
	title="The planes"
	lead="Each plane is one fill. A plane is told apart from the one under it by that fill alone."
>
	<ul class="divide-y divide-line overflow-hidden rounded-panel bg-surface">
		{#each planes as plane (plane.name)}
			<li class="flex items-center gap-4 px-5 py-3.5">
				<span
					class="size-10 shrink-0 rounded-control border border-line {plane.fill}"
					aria-hidden="true"
				></span>
				<div class="min-w-0 flex-1">
					<div class="flex flex-wrap items-baseline gap-x-3">
						<span class="text-sm font-medium text-ink">{plane.name}</span>
						<code class="font-mono text-sm text-ink-muted">{plane.token}</code>
					</div>
					<p class="text-sm text-ink-muted">{plane.holds}</p>
				</div>
			</li>
		{/each}
	</ul>
</SiteSection>

<SiteSection
	title="Nesting goes one way"
	lead="Canvas holds panels. A panel holds rows, sections and wells. A well holds content, never another well. When a panel seems to need a panel inside it, it needs a section: a heading, or a line between rows."
>
	<DoDont
		wrongNote="A panel in a panel. The inner one has to be outlined to be seen, and the outlines start to stack."
		rightNote="One panel, two sections, split by a single line. The chart is a well."
	>
		{#snippet wrong()}
			<div class="rounded-panel bg-surface p-4">
				<div class="text-sm font-semibold text-ink">Stepper</div>
				<div class="mt-3 border border-line-strong bg-surface p-3">
					<div class="text-sm font-medium text-ink">Controls</div>
					<div class="mt-2 h-8 border border-line-strong"></div>
				</div>
				<div class="mt-3 border border-line-strong bg-surface p-3">
					<div class="text-sm font-medium text-ink">Driver settings</div>
				</div>
			</div>
		{/snippet}
		{#snippet right()}
			<div class="divide-y divide-line overflow-hidden rounded-panel bg-surface">
				<div class="p-4">
					<div class="text-sm font-semibold text-ink">Controls</div>
					<div class="mt-2 h-8 rounded-control bg-well"></div>
				</div>
				<div class="p-4">
					<div class="text-sm font-semibold text-ink">Driver settings</div>
				</div>
			</div>
		{/snippet}
	</DoDont>
	<DoDont
		wrongNote="A group's name on a band of well. Across the panel a well is a shade off the canvas, so it reads as a gap in the panel with a word in it."
		rightNote="The name is a label on the list's own plane, with the rows' line above and below it."
	>
		{#snippet wrong()}
			<div class="divide-y divide-line overflow-hidden rounded-panel bg-surface text-sm">
				<div class="px-3 py-2.5 text-ink">Brick 2 x 4</div>
				<div class="bg-well px-3 py-1 text-ink-muted">Distributed</div>
				<div class="px-3 py-2.5 text-ink">Plate 2 x 2 corner</div>
				<div class="px-3 py-2.5 text-ink">Tile 1 x 1</div>
			</div>
		{/snippet}
		{#snippet right()}
			<div class="divide-y divide-line overflow-hidden rounded-panel bg-surface text-sm">
				<div class="px-3 py-2.5 text-ink">Brick 2 x 4</div>
				<div class="label px-3 py-1.5">Distributed</div>
				<div class="px-3 py-2.5 text-ink">Plate 2 x 2 corner</div>
				<div class="px-3 py-2.5 text-ink">Tile 1 x 1</div>
			</div>
		{/snippet}
	</DoDont>
</SiteSection>

<SiteSection
	title="Two kinds of line"
	lead="Both are 1px. There is no thicker line; emphasis comes from fill and color."
>
	<div class="grid gap-4 md:grid-cols-2">
		<Specimen code={`<ul class="divide-y divide-line">`}>
			<div class="label mb-3">line: divides items on one plane</div>
			<ul class="divide-y divide-line">
				{#each ['Plate 2 x 2 Corner', 'Tile, Round 1 x 1 Quarter', 'Brick 1 x 4'] as part (part)}
					<li class="py-2 text-sm text-ink">{part}</li>
				{/each}
			</ul>
		</Specimen>
		<Specimen code={`<Input />  <Button>Connect</Button>`}>
			<div class="label mb-3">line-strong: outlines a control</div>
			<div class="flex gap-2">
				<Input placeholder="ws://sorter.local:8000/ws" class="min-w-0 flex-1" />
				<Button>Connect</Button>
			</div>
			<p class="mt-3 text-sm text-ink-muted">
				A field is the one thing outlined, because the outline says "you can type here". Buttons are
				tints and need none.
			</p>
		</Specimen>
	</div>
</SiteSection>

<SiteSection
	title="Who owns a line"
	lead="A double line appears when two parts both draw the edge between them. So every line has one owner, and the owners are fixed."
>
	<Panel flush>
		<ul class="divide-y divide-line">
			<li class="px-5 py-3.5 text-sm">
				<span class="font-medium text-ink">A list or a table:</span>
				<span class="text-ink-muted"
					>the rows own the lines between them (<code class="font-mono">divide-y</code>). No line
					above the first row or below the last; the panel around them has none either.</span
				>
			</li>
			<li class="px-5 py-3.5 text-sm">
				<span class="font-medium text-ink">A panel:</span>
				<span class="text-ink-muted"
					>owns only the line above its footer. Its edges are its fill.</span
				>
			</li>
			<li class="px-5 py-3.5 text-sm">
				<span class="font-medium text-ink">The top bar:</span>
				<span class="text-ink-muted"
					>owns the line under it. Nothing below it draws a line at its top.</span
				>
			</li>
			<li class="px-5 py-3.5 text-sm">
				<span class="font-medium text-ink">A tab bar:</span>
				<span class="text-ink-muted"
					>owns the line under it, and the current tab's mark sits on that line, in place of it.</span
				>
			</li>
			<li class="px-5 py-3.5 text-sm">
				<span class="font-medium text-ink">Controls in a row:</span>
				<span class="text-ink-muted"
					>keep a gap of at least 8px. Choices that belong together are one control with no lines
					inside, like a segmented control.</span
				>
			</li>
		</ul>
	</Panel>
	<Specimen pad={false}>
		<Tabs
			label="Feed"
			inset
			bind:value={tab}
			items={[
				{ value: 'live', label: 'Live' },
				{ value: 'recent', label: 'Recent', count: 24 },
				{ value: 'errors', label: 'Errors', count: 0 }
			]}
		/>
		<ul class="divide-y divide-line">
			{#each ['Plate 2 x 2 Corner', 'Tile, Round 1 x 1 Quarter', 'Brick 1 x 4'] as part (part)}
				<li class="flex items-center justify-between px-5 py-2.5 text-sm text-ink">
					{part}<Badge tone="success">Distributed</Badge>
				</li>
			{/each}
		</ul>
		<div class="flex flex-wrap items-center gap-3 border-t border-line px-5 py-3">
			<SegmentedControl
				label="Move by"
				bind:value={unit}
				options={[
					{ value: 'duration', label: 'Duration' },
					{ value: 'degrees', label: 'Degrees' }
				]}
			/>
			<Button>Jog</Button>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="State is a fill"
	lead="Hover and press lay a faint fill over whatever plane is under them; the chosen item takes the primary's tint; keyboard focus draws a 2px primary ring. A line never changes weight."
>
	<Specimen>
		<div class="grid gap-6 md:grid-cols-2">
			<div class="flex flex-col gap-px">
				{#each ['Hover me', 'Press me', 'Chosen'] as label, i (label)}
					<button
						type="button"
						onclick={() => (chosen = i)}
						class="flex h-8 items-center px-3 text-left text-sm transition-colors {chosen === i
							? 'bg-primary-soft font-medium text-primary-ink'
							: 'text-ink-muted hover:bg-hover hover:text-ink active:bg-pressed'}"
					>
						{label}
					</button>
				{/each}
			</div>
			<p class="text-sm text-ink-muted">
				Tab to the list to see the focus ring. The fills are translucent, so the same token works on
				the canvas, a panel and a well.
			</p>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="A card you open"
	lead="A card that is one thing to open (a machine, a profile) is a link as big as the card. The pointer anywhere on it fills it a step, like any state: no shadow, no lift, no heavier line. A button inside it still does its own thing."
>
	<Specimen
		on="canvas"
		code={`<Card href="/machines/{machine.id}" label={machine.name}>
	...
	<Button size="sm" variant="ghost" icon={ExternalLink} label="Open its own page" href={local} />
</Card>`}
	>
		<div class="grid gap-(--gap-panels) md:grid-cols-2">
			{#each machines as machine (machine.id)}
				<Card href="/surfaces#{machine.id}" label={machine.name}>
					<div class="flex items-start gap-3">
						<span
							class="flex size-9 shrink-0 items-center justify-center rounded-control {machine.online
								? 'bg-success-soft text-success-ink'
								: 'bg-well text-ink-muted'}"
						>
							<Cpu size={18} />
						</span>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2">
								<span class="truncate font-semibold text-ink">{machine.name}</span>
								<Badge tone={machine.online ? 'success' : 'neutral'} dot
									>{machine.online ? 'Online' : 'Offline'}</Badge
								>
							</div>
							<p class="mt-0.5 truncate text-sm text-ink-muted">{machine.where}</p>
						</div>
						<Button
							size="sm"
							variant="ghost"
							icon={ExternalLink}
							label="Open its own page"
							href="/surfaces#{machine.id}-local"
						/>
					</div>
					<p class="mt-4 text-sm text-ink-muted">
						<span class="num font-medium text-ink">{machine.today.toLocaleString('en-US')}</span> parts
						sorted today
					</p>
				</Card>
			{/each}
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="The raised plane"
	lead="What floats is the one thing with a line around it, and it has no shadow: the line and the fill are enough. It closes on a click outside or Escape, and it never covers the thing that opened it."
>
	<Specimen>
		<Popover label="What is the raised plane">
			{#snippet trigger(props)}
				<Button {...props}>Open a popover</Button>
			{/snippet}
			<div class="font-medium text-ink">Raised</div>
			<p class="mt-1 text-ink-muted">
				A popover sits in the browser's top layer, so a panel's edge never clips it.
			</p>
		</Popover>
	</Specimen>
</SiteSection>

<SiteSection
	title="Media"
	lead="Camera feeds and photos sit on the media backdrop, dark in both modes, in a media tile: a strip on the surface with the name and the controls, then the picture to the tile's edges. The tile is the shape of its picture, so there is never a bar above and below it or down its sides; a layout gives it a width and the height follows. A tile that is only the picture puts its controls over it, on the scrim. Full screen, the tile fills the window on the media plane, until Exit full screen or Escape."
>
	<Specimen
		on="canvas"
		code={`<MediaTile title="C-Channel 2" expandable>
	{#snippet actions()}<Button size="sm" variant="ghost">-1°</Button>...{/snippet}
	{#snippet overlay()}<Badge tone="success" dot>Live</Badge>{/snippet}
	<img src={feed} alt="" class="size-full object-contain" />
</MediaTile>

<MediaTile title="Classification channel" header={false} expandable>
	<img src={feed} alt="" class="size-full object-contain" />
</MediaTile>`}
	>
		<div class="grid items-start gap-(--gap-panels) md:grid-cols-2">
			<MediaTile title="C-Channel 2" expandable>
				{#snippet actions()}
					<Button size="sm" variant="ghost">-1°</Button>
					<Button size="sm" variant="ghost">+1°</Button>
					<Button size="sm" variant="ghost" icon={RotateCw}>180°</Button>
				{/snippet}
				{#snippet overlay()}<Badge tone="success" dot>Live</Badge>{/snippet}
				<img src={sampleFeed(1280, 720)} alt="" class="size-full object-contain" />
			</MediaTile>
			<MediaTile title="Classification channel" header={false} expandable>
				{#snippet overlay()}<Badge tone="success" dot>Live</Badge>{/snippet}
				<img src={sampleFeed(800, 600)} alt="" class="size-full object-contain" />
			</MediaTile>
		</div>
	</Specimen>
</SiteSection>
