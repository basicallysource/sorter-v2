<!--
	The dashboard's Lot tab: what the lot being sorted holds, from
	GET /api/lots/{id}/summary. Its pieces and how many are identified, then
	those by color, by type and by part, and the sets it looks to have come
	from, when any stands out. Asked again every few seconds while the tab is
	in view; the new numbers replace the old in place.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { fetchLegoColors, findLegoColor } from '$lib/pieces/colors';
	import { sortingNow } from '$lib/stores/sortingNow.svelte';
	import BarList from '$lib/components/records/BarList.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import ColorChip from '$lib/components/ui/ColorChip.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';

	type CandidateSet = {
		set_num: string;
		name: string;
		year: number | null;
		image_url: string | null;
		total_pieces: number;
		have_pieces: number;
		share: number;
		distinctive_have: number;
		distinctive_total: number;
	};

	type Summary = {
		lot_id: string;
		name: string;
		pieces: number;
		identified: number;
		distinct_parts: number;
		colors: {
			color_id: string | null;
			color_name: string | null;
			hex: string | null;
			count: number;
		}[];
		types: { type: string; count: number }[];
		top_parts: { part_id: string; part_name: string | null; count: number }[];
		sets: CandidateSet[];
	};

	const REFRESH_MS = 10_000;
	const MAX_COLORS = 12;
	const MAX_TYPES = 8;
	const MAX_PARTS = 8;

	const ctx = getMachineContext();

	let summary = $state<Summary | null>(null);
	let error = $state<string | null>(null);

	const base = $derived(machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase());
	const now = $derived(sortingNow.for(base));
	const lotId = $derived(now?.run?.lot_id ?? null);
	const adding = $derived(now?.run?.adds_to_lot !== false);

	// The current run, if the top bar's menu has not asked for it yet, and the
	// machine's palette for a color the summary has no RGB for.
	$effect(() => {
		const from = base;
		void sortingNow.refresh(from, REFRESH_MS).catch(() => {});
		void fetchLegoColors(from).catch(() => {});
	});

	$effect(() => {
		const from = base;
		const id = lotId;
		untrack(() => {
			if (summary?.lot_id !== id) summary = null;
			error = null;
		});
		if (id === null) return;

		let stopped = false;
		const load = async () => {
			if (document.visibilityState !== 'visible') return;
			try {
				const res = await fetch(`${from}/api/lots/${id}/summary`);
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				const next = (await res.json()) as Summary;
				if (stopped) return;
				summary = next;
				error = null;
			} catch (e) {
				if (!stopped) error = e instanceof Error ? e.message : String(e);
			}
		};
		void load();
		const timer = setInterval(() => void load(), REFRESH_MS);
		document.addEventListener('visibilitychange', load);
		return () => {
			stopped = true;
			clearInterval(timer);
			document.removeEventListener('visibilitychange', load);
		};
	});

	const identifiedShare = $derived(
		summary && summary.pieces > 0 ? Math.round((summary.identified / summary.pieces) * 100) : null
	);
	const colors = $derived(
		(summary?.colors ?? []).slice(0, MAX_COLORS).map((c) => {
			const known = c.hex ? null : findLegoColor(c.color_id, c.color_name);
			return {
				key: c.color_id ?? '',
				name: c.color_name ?? known?.name ?? (c.color_id ? `Color ${c.color_id}` : 'No color'),
				rgb: c.hex ?? known?.hex ?? null,
				count: c.count
			};
		})
	);
	const types = $derived(
		(summary?.types ?? [])
			.slice(0, MAX_TYPES)
			.map((t) => ({ key: t.type, label: t.type, count: t.count }))
	);
	const parts = $derived((summary?.top_parts ?? []).slice(0, MAX_PARTS));

	function more(total: number, shown: number, what: string): string | null {
		const left = total - shown;
		return left > 0 ? `and ${left.toLocaleString()} more ${what}${left === 1 ? '' : 's'}` : null;
	}
</script>

<div class="h-full overflow-y-auto">
	{#if lotId === null}
		<p class="px-4 py-8 text-center text-sm text-ink-muted">
			{now === null ? '' : 'No lot selected'}
		</p>
	{:else}
		<div class="flex flex-col gap-4 px-3 py-3">
			<div>
				<div class="flex items-center justify-between gap-2">
					<span class="min-w-0 truncate text-sm font-medium text-ink">
						{summary?.name ?? now?.run?.lot_name ?? 'Lot'}
					</span>
					<Badge tone={adding ? 'neutral' : 'info'}>{adding ? 'Adding' : 'Re-sorting'}</Badge>
				</div>
				{#if summary}
					<p class="num mt-0.5 flex flex-wrap gap-x-1.5 text-sm text-ink-muted">
						<span><span class="text-ink">{summary.pieces.toLocaleString()}</span> pieces</span>
						{#if identifiedShare !== null}
							<span aria-hidden="true">·</span>
							<span><span class="text-ink">{identifiedShare}%</span> identified</span>
							<span aria-hidden="true">·</span>
							<span>
								<span class="text-ink">{summary.distinct_parts.toLocaleString()}</span> parts
							</span>
						{/if}
					</p>
				{/if}
			</div>

			{#if !summary}
				{#if error}
					<p class="text-sm text-danger-ink">Couldn't load the lot: {error}</p>
				{:else}
					<div class="flex justify-center py-4"><Spinner /></div>
				{/if}
			{:else}
				{#if colors.length > 0}
					{@const rest = more(summary.colors.length, colors.length, 'color')}
					<section class="flex flex-col gap-1.5">
						<h3 class="label">Colors</h3>
						<ul class="flex flex-wrap gap-x-3 gap-y-1.5 text-sm">
							{#each colors as color (color.key)}
								<li class="inline-flex min-w-0 items-center gap-1.5">
									<ColorChip class="text-ink" name={color.name} rgb={color.rgb} />
									<span class="num shrink-0 text-ink-muted">{color.count.toLocaleString()}</span>
								</li>
							{/each}
							{#if rest}<li class="text-ink-muted">{rest}</li>{/if}
						</ul>
					</section>
				{/if}

				{#if types.length > 0}
					{@const rest = more(summary.types.length, types.length, 'type')}
					<section class="flex flex-col gap-1.5">
						<h3 class="label">Types</h3>
						<BarList rows={types} labelWidth="sm:w-24" />
						{#if rest}<p class="text-sm text-ink-muted">{rest}</p>{/if}
					</section>
				{/if}

				{#if parts.length > 0}
					{@const rest = more(summary.distinct_parts, parts.length, 'part')}
					<section class="flex flex-col gap-1.5">
						<h3 class="label">Top parts</h3>
						<ul class="divide-y divide-line text-sm">
							{#each parts as part (part.part_id)}
								<li class="flex items-baseline gap-2 py-1">
									<span
										class="min-w-0 flex-1 truncate text-ink"
										title={part.part_name ?? part.part_id}
									>
										{part.part_name ?? part.part_id}
									</span>
									{#if part.part_name}
										<span class="num shrink-0 text-xs text-ink-muted">{part.part_id}</span>
									{/if}
									<span class="num w-12 shrink-0 text-right text-ink-muted">
										{part.count.toLocaleString()}
									</span>
								</li>
							{/each}
						</ul>
						{#if rest}<p class="text-sm text-ink-muted">{rest}</p>{/if}
					</section>
				{/if}

				{#if summary.sets.length > 0}
					<section class="flex flex-col gap-1.5">
						<h3 class="label">Sets</h3>
						<ul class="divide-y divide-line text-sm">
							{#each summary.sets as set (set.set_num)}
								<li class="flex items-center gap-3 py-2">
									<PartImage src={set.image_url} class="size-12 shrink-0" />
									<div class="min-w-0 flex-1">
										<div class="flex items-baseline justify-between gap-2">
											<span class="min-w-0 truncate font-medium text-ink" title={set.name}>
												{set.name}
											</span>
											<span class="num shrink-0 text-ink-muted">
												{set.set_num}{set.year ? ` · ${set.year}` : ''}
											</span>
										</div>
										<p class="num flex flex-wrap gap-x-1.5 text-ink-muted">
											<span>
												{set.have_pieces.toLocaleString()} of {set.total_pieces.toLocaleString()} pieces
											</span>
											{#if set.distinctive_total > 0}
												<span aria-hidden="true">·</span>
												<span>
													{set.distinctive_have.toLocaleString()} of {set.distinctive_total.toLocaleString()}
													distinctive
												</span>
											{/if}
										</p>
									</div>
								</li>
							{/each}
						</ul>
					</section>
				{/if}
			{/if}
		</div>
	{/if}
</div>
