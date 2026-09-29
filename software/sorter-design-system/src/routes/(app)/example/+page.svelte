<!-- The dashboard: cameras on the left, what the machine is doing on the right. -->
<script lang="ts">
	import Camera from '@lucide/svelte/icons/camera';
	import RotateCw from '@lucide/svelte/icons/rotate-cw';
	import House from '@lucide/svelte/icons/house';
	import Panel from '$lib/components/Panel.svelte';
	import Button from '$lib/components/Button.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Stat from '$lib/components/Stat.svelte';

	const cameras = ['C-Channel 2', 'C-Channel 3'];

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

{#snippet feed(name: string, wide = false)}
	<Panel flush class={wide ? 'md:col-span-2' : ''}>
		<div class="flex items-center justify-between gap-3 px-4 py-2">
			<span class="truncate text-sm font-medium text-ink">{name}</span>
			<div class="flex shrink-0 items-center gap-1">
				<Button size="sm" variant="ghost">-1°</Button>
				<Button size="sm" variant="ghost">+1°</Button>
				<Button size="sm" variant="ghost" icon={RotateCw}>180°</Button>
			</div>
		</div>
		<div
			class="flex items-center justify-center bg-media {wide ? 'aspect-[21/9]' : 'aspect-video'}"
		>
			<Camera size={24} class="text-ink-faint" />
		</div>
	</Panel>
{/snippet}

<div class="grid gap-4 p-4 sm:p-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
	<div class="grid content-start gap-4 md:grid-cols-2">
		{#each cameras as name (name)}
			{@render feed(name)}
		{/each}
		{@render feed('Classification channel', true)}
	</div>

	<div class="flex flex-col gap-4">
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

		<Panel flush>
			<div class="grid grid-cols-2 divide-x divide-line">
				<Stat label="Pieces a minute" value="14.7" />
				<Stat label="Sorted today" value="1,284" />
			</div>
		</Panel>

		<Panel title="Recent pieces" flush>
			<ul class="divide-y divide-line">
				{#each pieces as piece (piece.name)}
					<li class="flex gap-3 px-4 py-3">
						<div class="flex size-14 shrink-0 items-center justify-center bg-well">
							<span
								class="size-6 shadow-[inset_0_0_0_1px_rgb(0_0_0/0.15)]"
								style:background-color={piece.hex}
								aria-hidden="true"
							></span>
						</div>
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
