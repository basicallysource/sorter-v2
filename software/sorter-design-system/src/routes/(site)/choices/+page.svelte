<!--
	Every open choice side by side: each card carries the five choices as data
	attributes (the one being compared set to its option, the rest as chosen
	now), so it is drawn exactly as the whole site would be with that pick.
-->
<script lang="ts">
	import House from '@lucide/svelte/icons/house';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Trash from '@lucide/svelte/icons/trash-2';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Settings from '@lucide/svelte/icons/settings';
	import Camera from '@lucide/svelte/icons/camera';
	import Wrench from '@lucide/svelte/icons/wrench';
	import Check from '@lucide/svelte/icons/check';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Wordmark from '$lib/components/Wordmark.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Stat from '$lib/components/Stat.svelte';
	import Input from '$lib/components/Input.svelte';
	import Button from '$lib/components/Button.svelte';
	import Select from '$lib/components/Select.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Switch from '$lib/components/Switch.svelte';
	import Checkbox from '$lib/components/Checkbox.svelte';
	import Tabs from '$lib/components/Tabs.svelte';
	import { choices, dimensions, type Dimension } from '$lib/site/choices.svelte';

	function attrs(key: Dimension, value: string) {
		const all = { ...choices.current, [key]: value };
		return Object.fromEntries(Object.entries(all).map(([k, v]) => [`data-${k}`, v]));
	}

	let moveBy = $state<'duration' | 'degrees'>('degrees');
	let capture = $state(true);
	let upload = $state(true);
	let profile = $state('september');
	let tab = $state<'bins' | 'layers'>('bins');
</script>

<svelte:head><title>Choices · Sorter design system</title></svelte:head>

<PageHeader
	title="Choices"
	lead="What is still open, each drawn the same way in every option so they can be compared. Pick one letter per row; Try in the top bar puts a pick on every page."
/>

<p class="-mt-6 mb-10 text-sm text-ink-muted">Now: {choices.summary()}.</p>

{#snippet typeface()}
	<div class="flex flex-col gap-4">
		<div class="flex items-center justify-between gap-3">
			<Wordmark href="/choices" />
			<Badge tone="warning" dot>Not homed</Badge>
		</div>
		<div>
			<div class="text-xl font-semibold tracking-tight text-ink">General</div>
			<p class="mt-1 text-sm text-ink-muted">
				This machine, how this page reaches it, and how it looks.
			</p>
		</div>
		<div class="grid grid-cols-2 gap-px overflow-hidden rounded-control bg-line">
			<div class="bg-well"><Stat label="Pieces a minute" value="14.7" /></div>
			<div class="bg-well"><Stat label="Sorted today" value="1,284" /></div>
		</div>
		<div class="flex items-center justify-between gap-4">
			<div class="min-w-0">
				<div class="text-sm font-medium text-ink">Burst rate</div>
				<div class="text-sm text-ink-muted">The most photos to save in a minute.</div>
			</div>
			<Input type="number" value={6} unit="/min" class="w-28 shrink-0" />
		</div>
		<div class="flex flex-wrap gap-2">
			<Button variant="primary" icon={House}>Home</Button>
			<Button icon={RefreshCw}>Rescan</Button>
		</div>
	</div>
{/snippet}

{#snippet labels()}
	<div class="flex flex-col gap-4">
		<div class="grid grid-cols-2 gap-px overflow-hidden rounded-control bg-line">
			<div class="bg-well"><Stat label="Pieces a minute" value="14.7" /></div>
			<div class="bg-well"><Stat label="Sorted today" value="1,284" /></div>
		</div>
		<div class="flex flex-col gap-px">
			<div class="label px-2.5 pb-1.5">Hardware</div>
			<div
				class="flex h-(--size-nav-item) items-center gap-2.5 rounded-item bg-primary-soft px-2.5 text-sm font-medium text-primary-ink"
			>
				<Wrench size={16} />C-Channel 1
			</div>
			<div class="flex h-(--size-nav-item) items-center gap-2.5 px-2.5 text-sm text-ink-muted">
				<Camera size={16} />C-Channel 2
			</div>
		</div>
		<table class="data-table overflow-hidden rounded-control">
			<thead><tr><th>Day</th><th class="num">Pieces</th><th class="num">Unknown</th></tr></thead>
			<tbody>
				<tr><td>Mon 21</td><td class="num">3,120</td><td class="num">2.4%</td></tr>
				<tr><td>Tue 22</td><td class="num">2,984</td><td class="num">3.1%</td></tr>
			</tbody>
		</table>
	</div>
{/snippet}

{#snippet corners()}
	<div class="flex flex-col gap-4">
		<div class="flex flex-wrap items-center gap-2">
			<Button variant="primary" icon={House}>Home</Button>
			<Button>Rescan</Button>
			<Button variant="ghost" icon={Pencil} label="Rename" />
			<Badge tone="success" dot>Running</Badge>
		</div>
		<div class="grid grid-cols-2 gap-2">
			<Input value="Bench sorter" />
			<Select
				label="Profile"
				bind:value={profile}
				options={[
					{ value: 'september', label: 'September' },
					{ value: 'bulk', label: 'Bulk by color' }
				]}
			/>
		</div>
		<div class="flex flex-wrap items-center gap-4">
			<SegmentedControl
				label="Move by"
				bind:value={moveBy}
				options={[
					{ value: 'duration', label: 'Duration' },
					{ value: 'degrees', label: 'Degrees' }
				]}
			/>
			<Switch bind:checked={capture} label="Capture samples" />
			<Checkbox bind:checked={upload}>Upload</Checkbox>
		</div>
		<div class="rounded-control bg-well px-4 py-3 text-sm text-ink-muted">
			A well, sunk into the panel.
		</div>
	</div>
{/snippet}

{#snippet buttons()}
	<div class="flex flex-col gap-4">
		<div class="flex flex-wrap items-center gap-2">
			<Button variant="primary" icon={House}>Home</Button>
			<Button icon={RefreshCw}>Rescan</Button>
			<Button variant="ghost">Cancel</Button>
		</div>
		<div class="flex flex-wrap items-center gap-2">
			<Button size="sm" variant="primary">Save</Button>
			<Button size="sm">Duplicate</Button>
			<Button size="sm" variant="danger" icon={Trash}>Delete</Button>
			<Button size="sm" variant="ghost" icon={Settings} label="Settings" />
		</div>
		<div class="flex items-center justify-end gap-2 border-t border-line pt-3">
			<Button variant="ghost">Reset</Button>
			<Button variant="primary">Save</Button>
		</div>
	</div>
{/snippet}

{#snippet density()}
	<div class="-m-5 flex flex-col">
		<Tabs
			label="Bins"
			inset
			bind:value={tab}
			items={[
				{ value: 'bins', label: 'Bins', count: 36 },
				{ value: 'layers', label: 'Layers', count: 3 }
			]}
		/>
		<div class="divide-y divide-line">
			<div class="flex items-center justify-between gap-4 px-(--pad-panel) py-(--pad-row)">
				<div>
					<div class="text-sm font-medium text-ink">Capture samples</div>
					<div class="text-sm text-ink-muted">Save a photo of each part.</div>
				</div>
				<Switch bind:checked={capture} label="Capture samples" />
			</div>
			<div class="flex items-center justify-between gap-4 px-(--pad-panel) py-(--pad-row)">
				<div class="text-sm font-medium text-ink">Burst rate</div>
				<Input type="number" value={6} unit="/min" class="w-28" />
			</div>
			<div class="flex items-center justify-between gap-4 px-(--pad-panel) py-(--pad-row)">
				<div class="flex items-center gap-2 text-sm font-medium text-ink">
					Profile <Badge tone="success" dot>Running</Badge>
				</div>
				<div class="w-40">
					<Select
						label="Profile"
						bind:value={profile}
						options={[
							{ value: 'september', label: 'September' },
							{ value: 'bulk', label: 'Bulk by color' }
						]}
					/>
				</div>
			</div>
		</div>
		<div class="flex justify-end gap-2 border-t border-line px-(--pad-panel) py-3">
			<Button variant="primary">Save</Button>
		</div>
	</div>
{/snippet}

{#snippet sample(key: Dimension)}
	{#if key === 'font'}{@render typeface()}
	{:else if key === 'labels'}{@render labels()}
	{:else if key === 'corners'}{@render corners()}
	{:else if key === 'buttons'}{@render buttons()}
	{:else}{@render density()}{/if}
{/snippet}

{#each dimensions as dimension (dimension.key)}
	<SiteSection title={dimension.name}>
		<div class="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
			{#each dimension.options as option (option.value)}
				{@const inUse = choices.current[dimension.key] === option.value}
				<div
					{...attrs(dimension.key, option.value)}
					class="flex flex-col overflow-hidden rounded-panel bg-surface"
				>
					<div class="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
						<div class="flex min-w-0 items-center gap-3">
							<span
								class="flex size-7 shrink-0 items-center justify-center rounded-control bg-ink text-sm font-semibold text-surface"
								>{option.letter}</span
							>
							<div class="min-w-0">
								<div class="flex items-center gap-2">
									<span class="truncate text-sm font-medium text-ink">{option.name}</span>
									{#if option.today}<Badge>Today</Badge>{/if}
								</div>
								{#if option.detail}<div class="truncate text-xs text-ink-muted">
										{option.detail}
									</div>{/if}
							</div>
						</div>
						{#if inUse}
							<span class="flex shrink-0 items-center gap-1 text-sm text-primary-ink"
								><Check size={16} />In use</span
							>
						{:else}
							<Button size="sm" onclick={() => choices.set(dimension.key, option.value)}>Use</Button
							>
						{/if}
					</div>
					<div class="flex-1 p-5">
						{@render sample(dimension.key)}
					</div>
				</div>
			{/each}
		</div>
	</SiteSection>
{/each}
