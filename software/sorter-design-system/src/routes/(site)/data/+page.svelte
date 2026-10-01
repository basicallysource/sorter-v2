<script lang="ts">
	import Inbox from '@lucide/svelte/icons/inbox';
	import Plus from '@lucide/svelte/icons/plus';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Stat from '$lib/components/Stat.svelte';
	import KeyValue from '$lib/components/KeyValue.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Button from '$lib/components/Button.svelte';

	const runs = [
		{ day: 'Mon 21', pieces: 3120, rate: 14.1, unknown: 2.4, status: 'Done' },
		{ day: 'Tue 22', pieces: 2984, rate: 13.6, unknown: 3.1, status: 'Done' },
		{ day: 'Wed 23', pieces: 812, rate: 9.8, unknown: 7.9, status: 'Stopped' },
		{ day: 'Thu 24', pieces: 3405, rate: 14.9, unknown: 1.8, status: 'Done' },
		{ day: 'Fri 25', pieces: 1290, rate: 14.4, unknown: 2.2, status: 'Running' }
	];

	const bins = [
		{ name: 'L1 · S0 · B0', fill: 18 },
		{ name: 'L1 · S0 · B1', fill: 64 },
		{ name: 'L1 · S1 · B0', fill: 91 }
	];

	// Pieces a minute over an hour, one point every two minutes.
	const series = [
		11.2, 12.8, 13.1, 12.4, 14.0, 14.6, 13.9, 15.1, 14.7, 9.2, 6.1, 10.8, 13.4, 14.2, 14.9, 15.3,
		14.8, 14.1, 14.6, 15.0, 14.4, 13.8, 14.7, 15.2, 14.9, 14.3, 14.8, 15.4, 15.1, 14.7
	];
	const max = 20;
	const points = series
		.map(
			(v, i) =>
				`${((i / (series.length - 1)) * 100).toFixed(2)},${(40 - (v / max) * 40).toFixed(2)}`
		)
		.join(' ');

	function tone(status: string) {
		return status === 'Running' ? 'success' : status === 'Stopped' ? 'warning' : 'neutral';
	}
</script>

<svelte:head><title>Data · Sorter design system</title></svelte:head>

<PageHeader
	title="Data"
	lead="How numbers, records and states are shown: badges, stats, tables, facts, progress, charts, and what an empty list says."
	doc="components"
/>

<SiteSection
	title="Badges"
	lead="A short state or count beside what it describes: a tint and the tone's ink. The dot is round whatever the corners."
>
	<Specimen code={`<Badge tone="success" dot>Running</Badge>`}>
		<div class="flex flex-wrap items-center gap-2">
			<Badge>Idle</Badge>
			<Badge tone="primary">Selected</Badge>
			<Badge tone="info">Updating</Badge>
			<Badge tone="success" dot>Running</Badge>
			<Badge tone="warning" dot>Not homed</Badge>
			<Badge tone="danger" dot>Jammed</Badge>
			<Badge tone="success">Distributed</Badge>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="Stats"
	lead="A number and its name. Stats share one panel as a grid of cells: the gaps between the cells are the lines, so there is never one at the edge."
>
	<Specimen
		pad={false}
		code={`<div class="grid grid-cols-2 gap-px bg-line md:grid-cols-4">
	<div class="bg-surface"><Stat label="Pieces a minute" value="14.7" /></div>
	...
</div>`}
	>
		<div class="grid grid-cols-2 gap-px bg-line md:grid-cols-4">
			<div class="bg-surface"><Stat label="Pieces a minute" value="14.7" /></div>
			<div class="bg-surface"><Stat label="Sorted today" value="1,284" /></div>
			<div class="bg-surface">
				<Stat label="Unknown" value="2.4" unit="%" tone="warning" hint="31 of 1,284" />
			</div>
			<div class="bg-surface"><Stat label="Uptime" value="6:42" unit="h" /></div>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="Tables"
	lead="A head of labels, one line under it and between rows, no outer border and no vertical lines. Numbers are right-aligned in tabular figures. A row that opens something highlights under the pointer."
>
	<Panel title="Runs this week" flush>
		<div class="overflow-x-auto">
			<table class="data-table">
				<thead>
					<tr>
						<th>Day</th>
						<th class="num">Pieces</th>
						<th class="num">A minute</th>
						<th class="num">Unknown</th>
						<th>State</th>
					</tr>
				</thead>
				<tbody>
					{#each runs as run (run.day)}
						<tr class="is-link">
							<td>{run.day}</td>
							<td class="num">{run.pieces.toLocaleString('en-US')}</td>
							<td class="num">{run.rate.toFixed(1)}</td>
							<td class="num">{run.unknown.toFixed(1)}%</td>
							<td><Badge tone={tone(run.status)}>{run.status}</Badge></td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</Panel>
</SiteSection>

<SiteSection
	title="Facts"
	lead="Facts about one thing, one line between pairs. Mono for what someone might copy."
>
	<div class="max-w-md">
		<Panel title="This machine">
			<KeyValue
				items={[
					{ label: 'Version', value: '0.9.3' },
					{ label: 'Address', value: 'ws://sorter.local:8000/ws', mono: true },
					{ label: 'Machine ID', value: 'a41f09c2e7', mono: true },
					{ label: 'Uptime', value: '6 hours, 42 minutes' }
				]}
			/>
		</Panel>
	</div>
</SiteSection>

<SiteSection
	title="Progress"
	lead="How full, how far. A track, the fill in the primary, or in a status tone when the level means something."
>
	<div class="max-w-md">
		<Panel title="Bins" flush>
			<ul class="divide-y divide-line">
				{#each bins as bin (bin.name)}
					<li class="flex flex-col gap-2 px-5 py-3">
						<div class="flex items-baseline justify-between text-sm">
							<span class="num text-ink">{bin.name}</span>
							<span class="num text-ink-muted">{bin.fill}%</span>
						</div>
						<ProgressBar
							value={bin.fill}
							label="{bin.name} fill"
							tone={bin.fill >= 90 ? 'danger' : bin.fill >= 60 ? 'warning' : 'primary'}
						/>
					</li>
				{/each}
			</ul>
		</Panel>
	</div>
</SiteSection>

<SiteSection
	title="Charts"
	lead="Drawn in SVG on a well: the series 1.5px in the primary, gridlines in the divider color, labels at 12px. No chart library, no legend where one series needs none."
>
	<Panel title="Pieces a minute" description="The last hour." flush>
		<div class="mx-5 mb-5 bg-well p-4">
			<div class="relative h-40">
				<svg
					viewBox="0 0 100 40"
					preserveAspectRatio="none"
					class="absolute inset-0 h-full w-full"
					role="img"
					aria-label="Pieces a minute over the last hour, mostly near 14, with a dip to 6 about twenty minutes in"
				>
					{#each [0, 10, 20, 30, 40] as y (y)}
						<line
							x1="0"
							x2="100"
							y1={y}
							y2={y}
							stroke="var(--line)"
							stroke-width="1"
							vector-effect="non-scaling-stroke"
						/>
					{/each}
					<polyline
						{points}
						fill="none"
						stroke="var(--primary)"
						stroke-width="1.5"
						vector-effect="non-scaling-stroke"
					/>
				</svg>
			</div>
			<div class="mt-2 flex justify-between text-xs text-ink-muted">
				<span>60 min ago</span><span>30 min</span><span>now</span>
			</div>
		</div>
	</Panel>
</SiteSection>

<SiteSection
	title="Empty"
	lead="An empty list says what would be here and, when there is one, the action that fills it."
>
	<div class="max-w-xl">
		<Panel title="Sorting profiles">
			<EmptyState icon={Inbox} title="No profiles yet">
				A profile says which parts go to which bins.
				{#snippet action()}<Button variant="primary" icon={Plus}>New profile</Button>{/snippet}
			</EmptyState>
		</Panel>
	</div>
</SiteSection>
