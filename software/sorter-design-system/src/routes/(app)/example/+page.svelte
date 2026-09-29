<!--
	The dashboard. From lg up it fits the window: the cameras fill the left,
	the status and the numbers sit top right, and the recent pieces take the
	rest of the right column and scroll inside their panel. On a phone the
	status and its Home come first, then the cameras, then the pieces.
-->
<script lang="ts">
	import Camera from '@lucide/svelte/icons/camera';
	import RotateCw from '@lucide/svelte/icons/rotate-cw';
	import House from '@lucide/svelte/icons/house';
	import Panel from '$lib/components/Panel.svelte';
	import MediaTile from '$lib/components/MediaTile.svelte';
	import Button from '$lib/components/Button.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Stat from '$lib/components/Stat.svelte';

	const pieces = [
		{
			name: 'Plate 2 x 2 Corner',
			part: '2420',
			color: 'Red',
			hex: '#c91a09',
			group: 'Red plates',
			confidence: 72,
			price: 0.06,
			bin: 'L2 · S1 · B0'
		},
		{
			name: 'Tile, Round 1 x 1 Quarter',
			part: '25269',
			color: 'Dark Bluish Gray',
			hex: '#6c6e68',
			group: 'Round tiles',
			confidence: 80,
			price: 0.02,
			bin: 'L0 · S3 · B0'
		},
		{
			name: 'Plate, Round 1 x 1 with Flower Edge',
			part: '24866',
			color: 'White',
			hex: '#ffffff',
			group: 'Round plates',
			confidence: 52,
			price: 0.02,
			bin: 'L1 · S4 · B2'
		},
		{
			name: 'Brick 1 x 4',
			part: '3010',
			color: 'White',
			hex: '#ffffff',
			group: 'White bricks',
			confidence: 57,
			price: 0.11,
			bin: 'L2 · S0 · B1'
		},
		{
			name: 'Plate, Modified 1 x 2 with 1 Stud',
			part: '3794',
			color: 'Tan',
			hex: '#e4cd9e',
			group: 'Jumpers',
			confidence: 86,
			price: 0.03,
			bin: 'L3 · S2 · B0'
		},
		{
			name: 'Slope 45 2 x 1',
			part: '3040',
			color: 'Black',
			hex: '#05131d',
			group: 'Slopes',
			confidence: 91,
			price: 0.04,
			bin: 'L0 · S1 · B2'
		},
		{
			name: 'Technic Pin with Friction',
			part: '2780',
			color: 'Black',
			hex: '#05131d',
			group: 'Technic',
			confidence: 94,
			price: 0.01,
			bin: 'L3 · S4 · B1'
		}
	];

	function tone(confidence: number) {
		return confidence >= 70
			? 'text-success-ink'
			: confidence >= 55
				? 'text-warning-ink'
				: 'text-danger-ink';
	}
</script>

<svelte:head><title>Dashboard · Example app</title></svelte:head>

{#snippet rotate()}
	<Button size="sm" variant="ghost">-1°</Button>
	<Button size="sm" variant="ghost">+1°</Button>
	<Button size="sm" variant="ghost" icon={RotateCw}>180°</Button>
{/snippet}

{#snippet noFeed()}
	<Camera size={24} class="text-ink-faint" />
{/snippet}

<div
	class="grid gap-(--gap-panels) p-4 sm:p-6 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,1fr)_24rem] lg:grid-rows-[auto_minmax(0,1fr)]"
>
	<div class="flex flex-col gap-(--gap-panels) lg:col-start-2 lg:row-start-1">
		<Panel>
			<div class="flex items-start justify-between gap-4">
				<div class="min-w-0">
					<div class="flex items-center gap-2">
						<span class="text-base font-semibold text-ink">Standby</span>
						<Badge tone="warning" dot>Not homed</Badge>
					</div>
					<p class="mt-1 text-sm text-ink-muted">
						Home starts the hardware and moves every axis to its zero.
					</p>
				</div>
				<Button variant="primary" icon={House}>Home</Button>
			</div>
		</Panel>
		<div class="grid grid-cols-2 gap-px overflow-hidden rounded-panel bg-line">
			<div class="bg-surface"><Stat label="Pieces a minute" value="14.7" /></div>
			<div class="bg-surface"><Stat label="Sorted today" value="1,284" /></div>
		</div>
	</div>

	<div
		class="grid gap-(--gap-panels) md:grid-cols-2 lg:col-start-1 lg:row-span-2 lg:row-start-1 lg:min-h-0 lg:grid-rows-2"
	>
		<MediaTile title="C-Channel 2" actions={rotate} fill expandable>
			{@render noFeed()}
		</MediaTile>
		<MediaTile title="C-Channel 3" actions={rotate} fill expandable>
			{@render noFeed()}
		</MediaTile>
		<MediaTile
			title="Classification channel"
			actions={rotate}
			fill
			expandable
			class="md:col-span-2"
		>
			{@render noFeed()}
		</MediaTile>
	</div>

	<Panel title="Recent pieces" flush fill class="lg:col-start-2 lg:row-start-2">
		<ul class="divide-y divide-line">
			{#each pieces as piece (piece.name)}
				<li class="flex gap-3 px-4 py-3">
					<div class="flex size-14 shrink-0 items-center justify-center rounded-item bg-well">
						<span
							class="size-6 rounded-check border border-line"
							style:background-color={piece.hex}
							aria-hidden="true"
						></span>
					</div>
					<div class="min-w-0 flex-1">
						<div class="flex items-baseline justify-between gap-2">
							<span class="truncate text-sm font-medium text-ink" title={piece.name}
								>{piece.name}</span
							>
							<span class="num shrink-0 text-sm {tone(piece.confidence)}">{piece.confidence}%</span>
						</div>
						<div class="flex items-baseline justify-between gap-2 text-sm text-ink-muted">
							<span class="num">{piece.part}</span>
							<span class="num text-ink">${piece.price.toFixed(2)}</span>
						</div>
						<div class="mt-1.5 flex items-center justify-between gap-2">
							<span class="truncate text-sm text-ink-muted">{piece.color} · {piece.group}</span>
							<span class="num shrink-0 text-xs text-ink-muted">{piece.bin}</span>
						</div>
					</div>
				</li>
			{/each}
		</ul>
	</Panel>
</div>
