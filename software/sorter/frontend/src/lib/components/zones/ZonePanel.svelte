<!--
	A channel's zones, one row each: the ring, where pieces land (drop), the
	sliver before the exit where they are let off one at a time (precise), and
	where they leave (exit). Each says how big it is, can be made wider or
	narrower, says where it came from (drawn, found in the picture, learned from
	the pieces) and can be locked, so Find does not move it.
-->
<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import Pencil from '@lucide/svelte/icons/pencil';
	import ScanSearch from '@lucide/svelte/icons/scan-search';
	import X from '@lucide/svelte/icons/x';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import NudgeControl from '$lib/components/ui/NudgeControl.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import {
		isLocked,
		setLocked,
		setRadius,
		spanWidth,
		widen,
		zoneSpan,
		type ChannelZones,
		type Part,
		type Source,
		type ZoneName
	} from '$lib/zones/model';

	let {
		zones,
		editing = false,
		dirty = false,
		finding = false,
		saving = false,
		selected = null,
		note = '',
		watch = '',
		onchange,
		onselect,
		onfind,
		onedit,
		oncancel,
		onsave
	}: {
		zones: ChannelZones | null;
		editing?: boolean;
		dirty?: boolean;
		finding?: boolean;
		saving?: boolean;
		selected?: Part | null;
		// What Find found, or went wrong, in a sentence.
		note?: string;
		// What the machine has seen of its pieces while running, in a sentence.
		watch?: string;
		onchange: (zones: ChannelZones) => void;
		onselect?: (part: Part | null) => void;
		onfind: () => void;
		onedit: () => void;
		oncancel: () => void;
		onsave: () => void;
	} = $props();

	const ROWS: { part: Part; name: string; help: string; color?: string }[] = [
		{ part: 'ring', name: 'Ring', help: 'The band pieces ride, at the rim.' },
		{ part: 'drop', name: 'Drop', help: 'Where pieces land from the channel before.', color: 'rgb(0 128 255)' },
		{
			part: 'precise',
			name: 'Precise',
			help: 'The sliver before the exit, where pieces are let off one at a time.',
			color: 'rgb(255 0 255)'
		},
		{ part: 'exit', name: 'Exit', help: 'Where pieces leave, along the rim at the opening.', color: 'rgb(255 64 0)' }
	];

	const SOURCE: Record<Source, string> = {
		default: 'Not set yet',
		drawn: 'Set by hand',
		found: 'Found in the picture',
		learned: 'Learned from pieces'
	};

	let step = $state(1);

	function size(part: Part): string {
		if (!zones) return '';
		if (part === 'ring') return `${Math.round(zones.exit_radius)} px`;
		const span = zoneSpan(zones, part as ZoneName);
		return span ? `${Math.round(spanWidth(span))}°` : 'None';
	}

	function nudge(part: Part, side: 'left' | 'right') {
		if (!zones) return;
		const by = side === 'right' ? step : -step;
		if (part === 'ring') {
			// The ring grows or shrinks as one: the band and the exit's edge with it.
			const scale = (zones.exit_radius + by) / zones.exit_radius;
			let next = setRadius(zones, 'outer_radius', zones.outer_radius * scale);
			next = setRadius(next, 'exit_radius', zones.exit_radius * scale);
			onchange(setRadius(next, 'inner_radius', zones.inner_radius * scale));
		} else {
			onchange(widen(zones, part as ZoneName, by));
		}
	}
</script>

<Panel title="Zones" flush>
	{#snippet actions()}
		<Button icon={ScanSearch} loading={finding} disabled={saving} onclick={onfind}>Find</Button>
		{#if editing}
			<Button variant="ghost" icon={X} onclick={oncancel}>Cancel</Button>
			<Button variant="primary" icon={Check} loading={saving} disabled={!dirty} onclick={onsave}>Save</Button>
		{:else}
			<Button icon={Pencil} onclick={onedit}>Edit</Button>
		{/if}
	{/snippet}

	{#if note}
		<p class="px-(--pad-panel) pb-3 text-sm text-ink-muted">{note}</p>
	{/if}

	{#if zones}
		<div class="divide-y divide-line border-t border-line">
			{#each ROWS as row (row.part)}
				<div
					class="flex flex-col gap-2 px-(--pad-panel) py-(--pad-row) transition-colors sm:flex-row sm:items-center sm:justify-between sm:gap-6 {selected ===
					row.part
						? 'bg-primary-soft'
						: ''}"
					role="button"
					tabindex="0"
					onclick={() => onselect?.(row.part)}
					onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && onselect?.(row.part)}
				>
					<div class="min-w-0">
						<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
							{#if row.color}
								<span class="h-3 w-3 shrink-0 rounded-check" style:background={row.color}></span>
							{/if}
							<span class="text-sm font-medium text-ink">{row.name}</span>
							<span class="num text-sm text-ink-muted">{size(row.part)}</span>
							<Badge tone={zones.source[row.part] === 'learned' ? 'info' : 'neutral'}>
								{SOURCE[zones.source[row.part] ?? 'default']}
							</Badge>
						</div>
						<p class="mt-0.5 text-sm text-ink-muted">{row.help}</p>
					</div>
					<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
					<div class="flex shrink-0 items-center gap-3" onclick={(e) => e.stopPropagation()}>
						{#if editing}
							<NudgeControl
								bind:value={step}
								presets={[1, 5]}
								unit={row.part === 'ring' ? ' px' : '°'}
								max={row.part === 'ring' ? 200 : 90}
								label="Size of the {row.name.toLowerCase()}"
								leftLabel="Make the {row.name.toLowerCase()} smaller"
								rightLabel="Make the {row.name.toLowerCase()} bigger"
								amountLabel="Each press changes it by"
								disabled={isLocked(zones, row.part)}
								onnudge={(side) => nudge(row.part, side)}
							/>
						{/if}
						<span class="flex items-center gap-2">
							<span id="zone-lock-{row.part}" class="text-sm text-ink-muted">
								Lock the {row.name.toLowerCase()}
							</span>
							<Switch
								labelledby="zone-lock-{row.part}"
								checked={isLocked(zones, row.part)}
								onchange={(locked) => zones && onchange(setLocked(zones, row.part, locked))}
							/>
						</span>
					</div>
				</div>
			{/each}
		</div>
	{:else}
		<p class="px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">
			No zones yet. Find them in the picture, then adjust and save.
		</p>
	{/if}

	{#snippet footer()}
		<p class="mr-auto text-sm text-ink-muted">
			{watch || 'The zones change only when someone saves them. Lock a part to keep Find from moving it.'}
		</p>
	{/snippet}
</Panel>
