<!--
	The dashboard. From lg up it fits the window: the cameras on the left, laid
	out to their pictures so none has a bar (docs/layout.md, the dashboard
	layout), and one column on the right with the status, the numbers and the
	recent pieces, which scroll inside their panel. On a phone the status and
	its Home come first, then the cameras, then the pieces.
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

	// A part's picture: a shape with no background of its own, so it sits on the row.
	function partImage(hex: string) {
		const edge = 'stroke="#000000" stroke-opacity="0.28" stroke-width="2"';
		const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="112" height="112" viewBox="0 0 112 112"><circle cx="38" cy="34" r="11" fill="${hex}" ${edge}/><circle cx="74" cy="34" r="11" fill="${hex}" ${edge}/><rect x="14" y="38" width="84" height="46" rx="3" fill="${hex}" ${edge}/></svg>`;
		return `data:image/svg+xml,${encodeURIComponent(svg)}`;
	}

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

<!-- --feed is a picture's height over its width (9 / 16 for 16:9). The row is a
     size container, so the cameras' width can come from its height. -->
<div
	class="flex flex-col gap-(--gap-panels) p-4 sm:p-6 lg:[container-type:size] lg:min-h-0 lg:flex-1 lg:flex-row lg:justify-center"
	style="--feed: 0.5625"
>
	<div
		class="grid grid-cols-1 gap-(--gap-panels) md:grid-cols-2 lg:w-(--cameras) lg:shrink-0 lg:self-start"
		style="--cameras: min(100cqw - 19rem - var(--gap-panels), (100cqh - 2 * var(--size-control-lg) - (1 - var(--feed) / 2) * var(--gap-panels)) / (1.5 * var(--feed)))"
	>
		<MediaTile title="C-Channel 2" actions={rotate} expandable>
			{@render noFeed()}
		</MediaTile>
		<MediaTile title="C-Channel 3" actions={rotate} expandable>
			{@render noFeed()}
		</MediaTile>
		<MediaTile title="Classification channel" actions={rotate} expandable class="md:col-span-2">
			{@render noFeed()}
		</MediaTile>
	</div>

	<!-- Beside the cameras from lg up; on a phone the wrapper disappears, so the
	     status and the numbers come first and the pieces last. -->
	<div
		class="contents lg:flex lg:min-h-0 lg:max-w-160 lg:min-w-76 lg:flex-1 lg:flex-col lg:gap-(--gap-panels)"
	>
		<div class="flex flex-col gap-(--gap-panels) max-lg:order-first lg:shrink-0">
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

		<Panel title="Recent pieces" flush fill class="max-lg:order-last lg:flex-1">
			<ul class="divide-y divide-line">
				{#each pieces as piece (piece.name)}
					<li class="flex gap-3 px-4 py-3">
						<img src={partImage(piece.hex)} alt="" class="size-14 shrink-0 object-contain" />
						<div class="min-w-0 flex-1">
							<div class="flex items-baseline justify-between gap-2">
								<span class="truncate text-sm font-medium text-ink" title={piece.name}
									>{piece.name}</span
								>
								<span class="num shrink-0 text-sm {tone(piece.confidence)}"
									>{piece.confidence}%</span
								>
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
</div>
