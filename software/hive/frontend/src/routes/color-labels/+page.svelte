<script lang="ts">
	import {
		api,
		type BrickLinkColor,
		type ColorLabelQueueItem,
		type ColorLabelStats
	} from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Button } from '$lib/components/primitives';

	const BATCH = 30;
	const PREFETCH_WITHIN = 5;
	const SIMILAR_COUNT = 10;

	let colors = $state<BrickLinkColor[]>([]);
	let colorsById = $derived(new Map(colors.map((c) => [c.id, c])));
	let stats = $state<ColorLabelStats | null>(null);

	let items = $state<ColorLabelQueueItem[]>([]);
	let shownKeys = new Set<string>();
	let fetchOffset = 0;
	let hasMore = $state(true);
	let index = $state(0);

	let search = $state('');
	let loading = $state(true);
	let fetchingMore = $state(false);
	let submitting = $state(false);
	let error = $state<string | null>(null);

	const current = $derived(items[index] ?? null);

	// The pixel-average guess's nearest catalog color (used to highlight it and
	// for the one-click accept). Always a valid palette id when present.
	const guessColorId = $derived.by(() => {
		const id = current?.pixel_guess?.color_id;
		return id != null && colorsById.has(id) ? id : null;
	});

	const filteredColors = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (!q) return colors;
		return colors.filter(
			(c) => c.name.toLowerCase().includes(q) || String(c.id) === q
		);
	});

	// Perceptual color distance (CIE Lab / deltaE76) so the "closest to guess"
	// shortcut surfaces colors a human would actually confuse with the pixel
	// average (e.g. Tan vs Dark Tan) rather than RGB-nearest.
	function hexToLab(hex: string | null): [number, number, number] | null {
		if (!hex) return null;
		const m = hex.replace('#', '');
		if (m.length < 6) return null;
		const r = parseInt(m.slice(0, 2), 16);
		const g = parseInt(m.slice(2, 4), 16);
		const b = parseInt(m.slice(4, 6), 16);
		if ([r, g, b].some(Number.isNaN)) return null;
		const lin = (c: number) => {
			c /= 255;
			return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
		};
		const R = lin(r);
		const G = lin(g);
		const B = lin(b);
		const X = (R * 0.4124 + G * 0.3576 + B * 0.1805) / 0.95047;
		const Y = R * 0.2126 + G * 0.7152 + B * 0.0722;
		const Z = (R * 0.0193 + G * 0.1192 + B * 0.9505) / 1.08883;
		const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
		const fx = f(X);
		const fy = f(Y);
		const fz = f(Z);
		return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
	}

	const labById = $derived(
		new Map(colors.map((c) => [c.id, hexToLab(c.rgb)] as const))
	);

	// Rank the palette against the raw pixel-average RGB (more precise than the
	// already-rounded nearest color), excluding that nearest color since it's the
	// prominent one-click option.
	const similarColors = $derived.by(() => {
		const target = hexToLab(current?.pixel_guess?.rgb ?? null);
		if (!target) return [] as BrickLinkColor[];
		return colors
			.filter((c) => c.id !== guessColorId && labById.get(c.id) != null)
			.map((c) => {
				const lab = labById.get(c.id)!;
				const d = Math.hypot(lab[0] - target[0], lab[1] - target[1], lab[2] - target[2]);
				return { color: c, d };
			})
			.sort((a, b) => a.d - b.d)
			.slice(0, SIMILAR_COUNT)
			.map((x) => x.color);
	});

	function key(it: ColorLabelQueueItem): string {
		return `${it.machine_id}|${it.piece_uuid}`;
	}

	function errMsg(e: unknown, fallback: string): string {
		return e && typeof e === 'object' && 'error' in e
			? String((e as { error: unknown }).error)
			: fallback;
	}

	async function loadAll() {
		loading = true;
		error = null;
		items = [];
		shownKeys = new Set();
		fetchOffset = 0;
		hasMore = true;
		index = 0;
		try {
			const [colorsRes, statsRes] = await Promise.all([
				api.colorLabelColors(),
				api.colorLabelStats()
			]);
			// Drop non-answers: id<=0 is "(Not Applicable)"/[Unknown]; "Mx …" is
			// Modulex, a separate non-Lego system. (Speckle/Pearl/Chrome/Trans are
			// real Lego finishes and stay.)
			colors = colorsRes.results.filter((c) => c.id > 0 && !c.name.startsWith('Mx '));
			stats = statsRes;
			await fetchMore();
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to load labeling queue');
		} finally {
			loading = false;
		}
	}

	async function fetchMore() {
		if (fetchingMore || !hasMore) return;
		fetchingMore = true;
		try {
			const res = await api.colorLabelQueue({ onlyUnlabeled: true, limit: BATCH, offset: fetchOffset });
			fetchOffset += BATCH;
			hasMore = res.has_more;
			for (const it of res.items) {
				const k = key(it);
				if (!shownKeys.has(k)) {
					shownKeys.add(k);
					items.push(it);
				}
			}
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to load more pieces');
		} finally {
			fetchingMore = false;
		}
	}

	function maybePrefetch() {
		if (hasMore && items.length - index <= PREFETCH_WITHIN) void fetchMore();
	}

	function advance() {
		if (index < items.length - 1) index += 1;
		else index = items.length; // past the end → "all done" state
		maybePrefetch();
	}

	async function label(colorId: number) {
		if (!current || submitting) return;
		submitting = true;
		error = null;
		const it = current;
		try {
			const res = await api.submitColorLabel({
				machine_id: it.machine_id,
				piece_uuid: it.piece_uuid,
				color_id: colorId
			});
			if (stats) stats.labeled_by_me = res.labeled_by_me;
			search = '';
			advance();
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to save label');
		} finally {
			submitting = false;
		}
	}

	function skip() {
		if (!current) return;
		search = '';
		advance();
	}

	function back() {
		if (index > 0) index -= 1;
	}

	function onKey(e: KeyboardEvent) {
		if (e.target instanceof HTMLInputElement) return;
		if (e.key === 'Enter' && guessColorId != null) {
			e.preventDefault();
			void label(guessColorId);
		} else if (e.key === 'ArrowRight' || e.key === ' ') {
			e.preventDefault();
			skip();
		} else if (e.key === 'ArrowLeft') {
			e.preventDefault();
			back();
		}
	}

	$effect(() => {
		void loadAll();
	});
</script>

<svelte:head>
	<title>Color Labeling · Hive</title>
</svelte:head>

<svelte:window on:keydown={onKey} />

<div class="mb-6 flex items-end justify-between">
	<div>
		<h1 class="text-2xl font-bold text-text">Color Labeling</h1>
		<p class="text-sm text-text-muted">
			Pick the true BrickLink color of each synced piece. A
			<span class="font-medium">pixel-average guess</span> from the crops is offered as a starting point.
		</p>
	</div>
	{#if stats}
		<div class="text-right text-sm text-text-muted">
			<div><span class="text-text tabular-nums">{stats.labeled_by_me.toLocaleString()}</span> labeled by you</div>
			<div><span class="text-text tabular-nums">{stats.total_labelable.toLocaleString()}</span> labelable · {stats.total_labels.toLocaleString()} total</div>
		</div>
	{/if}
</div>

{#if error}
	<div class="mb-4 bg-primary/8 p-3 text-sm text-primary">{error}</div>
{/if}

{#if loading}
	<div class="flex justify-center py-16"><Spinner /></div>
{:else if !current}
	<div class="border border-border bg-surface p-10 text-center">
		<p class="text-sm text-text-muted">
			{items.length === 0
				? 'No pieces with crops available to label yet.'
				: 'All caught up — no more unlabeled pieces.'}
		</p>
		<div class="mt-4 flex justify-center">
			<Button variant="secondary" size="sm" onclick={loadAll}>Reload</Button>
		</div>
	</div>
{:else}
	<div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
		<!-- Piece under review -->
		<div class="border border-border bg-surface p-4">
			<div class="mb-3 flex flex-wrap items-center gap-2">
				<span class="text-sm font-medium text-text">
					{current.part.part_name || current.part.part_id || 'Unidentified'}
				</span>
				{#if current.part.part_id}
					<span class="text-xs text-text-muted">#{current.part.part_id}</span>
				{/if}
				<span class="text-xs text-text-muted">· {current.machine_name ?? 'machine'}</span>
			</div>

			<!-- Crops -->
			<div class="flex flex-wrap gap-2">
				{#each current.images as img (img.seq)}
					<img
						src={api.colorLabelImageUrl(current.machine_id, current.piece_uuid, img.seq)}
						alt={`crop ${img.seq}`}
						loading="lazy"
						title={`seq ${img.seq}${img.source ? ` · ${img.source}` : ''}`}
						class="h-28 w-28 border-2 bg-transparent object-contain {img.used ? 'border-success' : 'border-border'}"
					/>
				{/each}
			</div>

			<!-- Pixel-average guess computed from the crops above -->
			<div class="mt-4 flex items-center gap-3 border-t border-border pt-3">
				{#if current.pixel_guess}
					<span
						class="h-10 w-10 shrink-0 border border-border"
						style={`background:#${current.pixel_guess.rgb}`}
						title={`average pixel color #${current.pixel_guess.rgb}`}
					></span>
					<div class="min-w-0 text-xs text-text-muted">
						<div class="uppercase tracking-wide text-[10px]">Pixel-average guess</div>
						<div class="mt-0.5 flex items-center gap-1.5">
							{#if guessColorId != null}
								{@const gc = colorsById.get(guessColorId)}
								<span class="inline-block h-3.5 w-3.5 border border-border" style={`background:#${gc?.rgb ?? '000'}`}></span>
							{/if}
							<span class="text-text">{current.pixel_guess.color_name}</span>
							<span>({current.pixel_guess.color_id})</span>
							<span class="ml-2">nearest of {current.pixel_guess.sample_count} crop{current.pixel_guess.sample_count === 1 ? '' : 's'}</span>
						</div>
					</div>
				{:else}
					<span class="text-xs text-text-muted">No pixel guess — crops unavailable.</span>
				{/if}
			</div>
		</div>

		<!-- Palette picker -->
		<div class="flex flex-col border border-border bg-surface p-4">
			<div class="mb-3 flex items-center justify-between">
				<span class="text-sm font-medium text-text">True color</span>
				<div class="flex gap-1.5">
					<Button variant="ghost" size="sm" onclick={back} disabled={index === 0}>← Back</Button>
					<Button variant="secondary" size="sm" onclick={skip} disabled={submitting}>Skip →</Button>
				</div>
			</div>

			{#if guessColorId != null}
				{@const gc = colorsById.get(guessColorId)}
				<button
					class="mb-3 flex items-center gap-2 border border-success/60 bg-success/8 px-3 py-2 text-sm text-text hover:bg-success/15 disabled:opacity-50"
					onclick={() => label(guessColorId!)}
					disabled={submitting}
				>
					<span class="inline-block h-4 w-4 border border-border" style={`background:#${gc?.rgb ?? '000'}`}></span>
					<span>Use guess — <span class="font-medium">{gc?.name}</span></span>
					<span class="ml-auto text-xs text-text-muted">Enter</span>
				</button>
			{/if}

			{#snippet swatch(color: BrickLinkColor)}
				<button
					class="group flex flex-col items-center gap-1 border p-1 hover:border-primary disabled:opacity-50 {color.id ===
					guessColorId
						? 'border-success'
						: 'border-border'}"
					title={`${color.name} (${color.id})`}
					onclick={() => label(color.id)}
					disabled={submitting}
				>
					<span
						class="h-9 w-full border border-border {color.is_trans ? 'opacity-70' : ''}"
						style={`background:#${color.rgb ?? '000'}`}
					></span>
					<span class="w-full truncate text-center text-[10px] leading-tight text-text-muted group-hover:text-text">
						{color.name}
					</span>
				</button>
			{/snippet}

			{#if !search.trim() && similarColors.length > 0}
				<div class="mb-3">
					<div class="mb-1.5 text-xs font-medium text-text-muted">Closest to guess</div>
					<div class="grid grid-cols-4 gap-1.5">
						{#each similarColors as color (color.id)}
							{@render swatch(color)}
						{/each}
					</div>
				</div>
				<div class="mb-2 text-xs font-medium text-text-muted">All colors</div>
			{/if}

			<input
				type="text"
				bind:value={search}
				placeholder="Search colors…"
				class="mb-3 w-full border border-border bg-bg px-3 py-1.5 text-sm text-text placeholder:text-text-muted focus:border-primary focus:outline-none"
			/>

			<div class="grid max-h-[60vh] grid-cols-4 gap-1.5 overflow-y-auto pr-1">
				{#each filteredColors as color (color.id)}
					{@render swatch(color)}
				{/each}
			</div>
			{#if filteredColors.length === 0}
				<p class="py-4 text-center text-xs text-text-muted">No colors match “{search}”.</p>
			{/if}
		</div>
	</div>

	<div class="mt-3 flex items-center gap-3 text-xs text-text-muted">
		{#if submitting}<Spinner />{/if}
		<span>Keys: <span class="text-text">Enter</span> accept prediction · <span class="text-text">→</span>/<span class="text-text">Space</span> skip · <span class="text-text">←</span> back</span>
	</div>
{/if}
