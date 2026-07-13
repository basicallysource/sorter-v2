<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		type BrickLinkColor,
		type ColorLabelPieceDetail,
		type PossibleCropCandidate
	} from '$lib/api';
	import * as nav from '$lib/colorLabelNav';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Button } from '$lib/components/primitives';
	import ArrowLeft from 'lucide-svelte/icons/arrow-left';
	import ArrowRight from 'lucide-svelte/icons/arrow-right';
	import Check from 'lucide-svelte/icons/check';
	import Circle from 'lucide-svelte/icons/circle';
	import CircleCheck from 'lucide-svelte/icons/circle-check';
	import CircleDot from 'lucide-svelte/icons/circle-dot';
	import Sparkles from 'lucide-svelte/icons/sparkles';

	type CharState = 'empty' | 'progress' | 'ready';

	const SIMILAR_COUNT = 8;
	const ZONE_LABEL: Record<number, string> = { 0: 'mid', 1: 'drop', 2: 'exit', 3: 'precise' };
	// Non-basic finishes: a piece is far likelier a plain solid color than a
	// pearl/metallic/trans/etc, so these get down-weighted in the "closest" list.
	const EXOTIC_FINISH =
		/pearl|metallic|chrome|satin|trans|glow|speckle|glitter|glitr|milky|opal|iridescent|holo|copper|bionicle|\bgold\b|\bsilver\b/i;

	const machineId = $derived(page.params.machine_id ?? '');
	const pieceUuid = $derived(page.params.piece_uuid ?? '');
	const pieceKey = $derived(`${machineId}|${pieceUuid}`);

	let colors = $state<BrickLinkColor[]>([]);
	let colorsById = $derived(new Map(colors.map((c) => [c.id, c])));

	let detail = $state<ColorLabelPieceDetail | null>(null);
	let myColorId = $state<number | null>(null); // saved color for THIS piece (restored)
	let loading = $state(true);
	let error = $state<string | null>(null);
	let submitting = $state(false);
	let search = $state('');
	let pos = $state<{ index: number; total: number; hasMore: boolean }>({ index: -1, total: 0, hasMore: true });

	// Same-piece crops
	let cropCandidates = $state<PossibleCropCandidate[]>([]);
	let cropSelected = $state<Set<number>>(new Set());
	let cropArrivalTs: string | null = null;
	let cropLoading = $state(false);
	let cropSaving = $state(false);
	let cropSaved = $state(false); // a selection is committed to the db
	let cropDirty = $state(false); // toggled since last save/load
	let cropError = $state<string | null>(null);

	const guessColorId = $derived.by(() => {
		const id = detail?.pixel_guess?.color_id;
		return id != null && colorsById.has(id) ? id : null;
	});

	// --- Per-characteristic completion state (extensible) ---------------------
	const colorState = $derived<CharState>(myColorId != null ? 'ready' : 'empty');
	const piecesState = $derived<CharState>(
		cropCandidates.length === 0 ? 'empty' : cropDirty ? 'progress' : cropSaved ? 'ready' : 'empty'
	);
	// Add future piece characteristics here; the summary bar + CTA derive from it.
	const characteristics = $derived([
		{ key: 'color', label: 'Color', state: colorState },
		{ key: 'pieces', label: 'Same piece', state: piecesState }
	]);
	const touched = $derived(characteristics.filter((c) => c.state !== 'empty'));
	const ctaLabel = $derived.by(() => {
		if (touched.length === 0) return 'Skip';
		if (touched.length === characteristics.length) return 'Continue';
		return 'Accept ' + touched.map((c) => c.label.toLowerCase()).join(' + ');
	});

	function stateBorder(state: CharState): string {
		return state === 'ready'
			? 'border-success/40'
			: state === 'progress'
				? 'border-warning/50'
				: 'border-border';
	}

	const filteredColors = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (!q) return colors;
		return colors.filter((c) => c.name.toLowerCase().includes(q) || String(c.id) === q);
	});

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

	const labById = $derived(new Map(colors.map((c) => [c.id, hexToLab(c.rgb)] as const)));

	function isExotic(c: BrickLinkColor): boolean {
		return c.is_trans || EXOTIC_FINISH.test(c.name);
	}

	// Rank the palette against the guess, but push exotic finishes way down so the
	// shortlist is dominated by plain solid colors (a piece is rarely pearl/metal).
	const similarColors = $derived.by(() => {
		const target = hexToLab(detail?.pixel_guess?.rgb ?? null);
		if (!target) return [] as BrickLinkColor[];
		return colors
			.filter((c) => c.id !== guessColorId && labById.get(c.id) != null)
			.map((c) => {
				const lab = labById.get(c.id)!;
				const d = Math.hypot(lab[0] - target[0], lab[1] - target[1], lab[2] - target[2]);
				return { color: c, d: d + (isExotic(c) ? 55 : 0) };
			})
			.sort((a, b) => a.d - b.d)
			.slice(0, SIMILAR_COUNT)
			.map((x) => x.color);
	});

	function errMsg(e: unknown, fallback: string): string {
		return e && typeof e === 'object' && 'error' in e
			? String((e as { error: unknown }).error)
			: fallback;
	}

	async function load(mid: string, puid: string, k: string) {
		loading = true;
		error = null;
		try {
			if (colors.length === 0) colors = await nav.getColors();
			const [d, crops] = await Promise.all([
				api.colorLabelPieceDetail(mid, puid),
				api.possibleCrops(mid, puid)
			]);
			if (pieceKey !== k) return; // navigated away mid-load
			detail = d;
			myColorId = d.my_label?.color_id ?? null;
			cropCandidates = crops.candidates;
			cropArrivalTs = crops.arrival_ts;
			cropDirty = false;
			const savedPos = crops.my_link.filter((m) => m.is_same).map((m) => m.local_id);
			if (crops.my_link.length > 0) {
				const present = new Set(crops.candidates.map((c) => c.local_id));
				cropSelected = new Set(savedPos.filter((id) => present.has(id)));
				cropSaved = true;
			} else {
				cropSelected = new Set(crops.candidates.filter((c) => c.predicted).map((c) => c.local_id));
				cropSaved = false;
			}
			pos = nav.position({ machine_id: mid, piece_uuid: puid });
		} catch (e: unknown) {
			if (pieceKey === k) error = errMsg(e, 'Failed to load piece');
		} finally {
			if (pieceKey === k) loading = false;
		}
	}

	function gotoKey(k: nav.PieceKey) {
		void goto(`/piece-bboxes/${k.machine_id}/${encodeURIComponent(k.piece_uuid)}`);
	}

	async function goNext() {
		search = '';
		const next = await nav.nextAfter({ machine_id: machineId, piece_uuid: pieceUuid });
		if (next) gotoKey(next);
		else void goto('/piece-bboxes');
	}

	async function goPrev() {
		search = '';
		const prev = await nav.prevBefore({ machine_id: machineId, piece_uuid: pieceUuid });
		if (prev) gotoKey(prev);
		else void goto('/piece-bboxes');
	}

	// Pick a color: writes immediately and highlights with a check. Does NOT
	// advance — the summary bar / Enter is what moves on.
	async function pickColor(colorId: number) {
		if (submitting) return;
		submitting = true;
		error = null;
		try {
			await api.submitColorLabel({ machine_id: machineId, piece_uuid: pieceUuid, color_id: colorId });
			myColorId = colorId;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to save color');
		} finally {
			submitting = false;
		}
	}

	function toggleCrop(localId: number) {
		const s = new Set(cropSelected);
		if (s.has(localId)) s.delete(localId);
		else s.add(localId);
		cropSelected = s;
		cropDirty = true;
	}

	async function saveCrops() {
		if (cropSaving || cropCandidates.length === 0) return;
		cropSaving = true;
		cropError = null;
		const members = cropCandidates.map((c) => ({
			local_id: c.local_id,
			is_same: cropSelected.has(c.local_id),
			was_predicted: c.predicted
		}));
		try {
			await api.savePieceCropLink({
				machine_id: machineId,
				piece_uuid: pieceUuid,
				arrival_ts: cropArrivalTs ? Date.parse(cropArrivalTs) / 1000 : null,
				members
			});
			cropSaved = true;
			cropDirty = false;
		} catch (e: unknown) {
			cropError = errMsg(e, 'Failed to save selection');
		} finally {
			cropSaving = false;
		}
	}

	// The summary action: commit anything still in progress, then move on.
	async function commitAndAdvance() {
		if (cropDirty) await saveCrops();
		await goNext();
	}

	function onKey(e: KeyboardEvent) {
		if (e.target instanceof HTMLInputElement) return;
		if (e.key === 'Enter') {
			e.preventDefault();
			void commitAndAdvance();
		} else if (e.key === 'ArrowRight' || e.key === ' ') {
			e.preventDefault();
			void goNext();
		} else if (e.key === 'ArrowLeft') {
			e.preventDefault();
			void goPrev();
		}
	}

	// Reload whenever the route points at a different piece.
	$effect(() => {
		const mid = machineId;
		const puid = pieceUuid;
		if (!mid || !puid) return;
		void load(mid, puid, `${mid}|${puid}`);
	});
</script>

<svelte:head>
	<title>Label piece · Hive</title>
</svelte:head>

<svelte:window on:keydown={onKey} />

<div class="mb-4 flex items-center justify-between gap-3">
	<a href="/piece-bboxes" class="flex items-center gap-1 text-sm text-text-muted hover:text-text">
		<ArrowLeft size={14} /> All pieces
	</a>
	{#if pos.total > 0 && pos.index >= 0}
		<span class="text-xs text-text-muted tabular-nums">{pos.index + 1} of {pos.total}{pos.hasMore ? '+' : ''}</span>
	{/if}
</div>

{#snippet statusBadge(state: CharState)}
	{#if state === 'ready'}
		<span class="flex items-center gap-1 text-xs text-success"><CircleCheck size={13} /> Ready</span>
	{:else if state === 'progress'}
		<span class="flex items-center gap-1 text-xs text-warning"><CircleDot size={13} /> In progress</span>
	{:else}
		<span class="flex items-center gap-1 text-xs text-text-muted"><Circle size={13} /> Not started</span>
	{/if}
{/snippet}

{#if error}
	<div class="mb-4 bg-primary/8 p-3 text-sm text-primary">{error}</div>
{/if}

{#if loading}
	<div class="flex justify-center py-16"><Spinner /></div>
{:else if !detail}
	<div class="border border-border bg-surface p-10 text-center">
		<p class="text-sm text-text-muted">Piece not found.</p>
	</div>
{:else}
	<!-- Summary + advance (top): reflects what's done across every characteristic -->
	<div class="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 border border-border bg-surface p-3">
		<Button variant="ghost" size="sm" onclick={goPrev}><ArrowLeft size={14} /> Back</Button>
		<div class="flex flex-wrap items-center gap-x-4 gap-y-1">
			{#each characteristics as ch (ch.key)}
				<span class="flex items-center gap-1.5 text-sm text-text-muted">
					{ch.label}: {@render statusBadge(ch.state)}
				</span>
			{/each}
		</div>
		<div class="ml-auto flex items-center gap-2">
			<span class="hidden text-xs text-text-muted md:inline">Enter · →/Space skip · ← back</span>
			<Button
				variant={touched.length > 0 ? 'primary' : 'secondary'}
				size="sm"
				loading={cropSaving}
				onclick={commitAndAdvance}
			>
				{ctaLabel} <ArrowRight size={14} />
			</Button>
		</div>
	</div>

	<div class="flex flex-col gap-6 lg:flex-row lg:items-start">
		<div class="flex min-w-0 flex-col gap-6 lg:flex-1">
			<!-- Piece under review -->
			<div class="border border-border bg-surface p-4">
			<div class="mb-3 flex flex-wrap items-center gap-2">
				<span class="text-sm font-medium text-text">
					{detail.part.part_name || detail.part.part_id || 'Unidentified'}
				</span>
				{#if detail.part.part_id}
					<span class="text-xs text-text-muted">#{detail.part.part_id}</span>
				{/if}
				<span class="text-xs text-text-muted">· {detail.machine_name ?? 'machine'}</span>
			</div>

			<div class="flex flex-wrap gap-2">
				{#each detail.images as img (img.seq)}
					<img
						src={api.colorLabelImageUrl(machineId, pieceUuid, img.seq)}
						alt={`crop ${img.seq}`}
						loading="lazy"
						title={`seq ${img.seq}${img.source ? ` · ${img.source}` : ''}`}
						class="h-28 w-28 border-2 bg-transparent object-contain {img.used ? 'border-success' : 'border-border'}"
					/>
				{/each}
			</div>

			<div class="mt-4 flex items-center gap-3 border-t border-border pt-3">
				{#if detail.pixel_guess}
					<span
						class="h-10 w-10 shrink-0 border border-border"
						style={`background:#${detail.pixel_guess.rgb}`}
						title={`average pixel color #${detail.pixel_guess.rgb}`}
					></span>
					<div class="min-w-0 text-xs text-text-muted">
						<div class="text-xs font-semibold uppercase tracking-wider">Pixel-average guess</div>
						<div class="mt-0.5 flex items-center gap-1.5">
							{#if guessColorId != null}
								{@const gc = colorsById.get(guessColorId)}
								<span class="inline-block h-3.5 w-3.5 border border-border" style={`background:#${gc?.rgb ?? '000'}`}></span>
							{/if}
							<span class="text-text">{detail.pixel_guess.color_name}</span>
							<span>({detail.pixel_guess.color_id})</span>
							<span class="ml-2">nearest of {detail.pixel_guess.sample_count} crop{detail.pixel_guess.sample_count === 1 ? '' : 's'}</span>
						</div>
					</div>
				{:else}
					<span class="text-xs text-text-muted">No pixel guess — crops unavailable.</span>
				{/if}
			</div>
		</div>

			<!-- Same physical piece across the upstream channels -->
			<div class="border bg-surface p-4 {stateBorder(piecesState)}">
			<div class="mb-1 flex flex-wrap items-center justify-between gap-2">
				<div class="flex items-center gap-2">
					<span class="text-sm font-medium text-text">Same piece across channels</span>
					{@render statusBadge(piecesState)}
				</div>
				<div class="flex items-center gap-2">
					<span class="text-xs text-text-muted tabular-nums">
						{cropSelected.size} of {cropCandidates.length} selected
					</span>
					<Button
						variant={cropDirty ? 'primary' : 'secondary'}
						size="sm"
						loading={cropSaving}
						disabled={cropCandidates.length === 0 || cropLoading}
						onclick={saveCrops}
					>
						Accept
					</Button>
				</div>
			</div>
			<p class="mb-3 text-sm text-text-muted">
				Our guess of which upstream C2/C3 crops are this same physical piece, ranked by a
				time-and-angle heuristic. Keep or drop our picks and add any we missed, then
				<span class="font-medium">Accept</span>.
			</p>

			{#if cropLoading}
				<div class="flex justify-center py-8"><Spinner /></div>
			{:else if cropError}
				<div class="bg-primary/8 p-3 text-sm text-primary">{cropError}</div>
			{:else if cropCandidates.length === 0}
				<p class="py-4 text-sm text-text-muted">No candidate crops in range for this piece.</p>
			{:else}
				<div class="flex max-h-[42vh] flex-wrap gap-2 overflow-y-auto pr-1">
					{#each cropCandidates as c (c.local_id)}
						{@const selected = cropSelected.has(c.local_id)}
						<button
							type="button"
							onclick={() => toggleCrop(c.local_id)}
							title={`C${c.channel} · ${ZONE_LABEL[c.zone_code ?? 0] ?? '?'} · ${c.dt != null ? c.dt + 's before arrival' : 'unknown dt'} · ${c.com_forward_to_exit_deg != null ? Math.round(c.com_forward_to_exit_deg) + '° to exit' : ''} · score ${c.score}${c.predicted ? ' · our pick' : ''}`}
							class="relative flex flex-col items-center gap-1 border-2 p-1 hover:border-primary {selected
								? 'border-success bg-success/10'
								: 'border-border opacity-70 hover:opacity-100'}"
						>
							{#if c.available}
								<img
									src={api.channelCropLabelImageUrl(machineId, c.local_id)}
									alt={`crop ${c.local_id}`}
									loading="lazy"
									class="h-16 w-16 bg-transparent object-contain"
								/>
							{:else}
								<div class="flex h-16 w-16 items-center justify-center border border-dashed border-border text-xs text-text-muted">
									evicted
								</div>
							{/if}
							<span class="flex items-center gap-1 text-xs {selected ? 'text-text' : 'text-text-muted'}">
								{#if selected}<Check size={12} class="text-success" />{/if}
								C{c.channel}·{c.dt}s
							</span>
							{#if c.predicted}
								<span class="absolute right-0.5 top-0.5 flex items-center bg-info/80 p-0.5 text-white" title="our prediction"><Sparkles size={11} /></span>
							{/if}
						</button>
					{/each}
				</div>
			{/if}
			</div>
		</div>

		<!-- Color picker -->
		<div class="flex flex-col border bg-surface p-4 lg:w-96 {stateBorder(colorState)}">
			<div class="mb-3 flex items-center justify-between gap-2">
				<span class="text-sm font-medium text-text">True color</span>
				{@render statusBadge(colorState)}
			</div>

			{#snippet colorRow(color: BrickLinkColor, isGuess: boolean)}
				{@const selected = color.id === myColorId}
				<button
					class="flex items-center gap-2 border px-2 py-0.5 text-left hover:border-primary disabled:opacity-50 {selected
						? 'border-success bg-success/10'
						: isGuess
							? 'border-info/60 bg-info/[0.06]'
							: 'border-border'}"
					title={`${color.name} (${color.id})`}
					onclick={() => pickColor(color.id)}
					disabled={submitting}
				>
					<span
						class="h-5 w-5 shrink-0 border border-border {color.is_trans ? 'opacity-70' : ''}"
						style={`background:#${color.rgb ?? '000'}`}
					></span>
					<span class="min-w-0 flex-1 truncate text-sm {selected ? 'text-text' : 'text-text-muted'}">
						{color.name}{#if isGuess}<span class="ml-1 text-xs text-info">· guess</span>{/if}
					</span>
					{#if selected}<Check size={14} class="shrink-0 text-success" />{/if}
				</button>
			{/snippet}

			{#if guessColorId != null}
				{@const gc = colorsById.get(guessColorId)}
				{#if gc}
					<div class="mb-3">
						{@render colorRow(gc, true)}
					</div>
				{/if}
			{/if}

			{#if !search.trim() && similarColors.length > 0}
				<div class="mb-1.5 text-xs font-semibold uppercase tracking-wider text-text-muted">Closest to guess</div>
				<div class="mb-3 flex flex-col gap-0.5">
					{#each similarColors as color (color.id)}
						{@render colorRow(color, false)}
					{/each}
				</div>
				<div class="mb-1.5 text-xs font-semibold uppercase tracking-wider text-text-muted">All colors</div>
			{/if}

			<input
				type="text"
				bind:value={search}
				placeholder="Search colors…"
				class="mb-3 w-full border border-border bg-bg px-3 py-1.5 text-sm text-text placeholder:text-text-muted focus:border-primary focus:outline-none"
			/>

			<div class="flex max-h-[46vh] flex-col gap-0.5 overflow-y-auto pr-1">
				{#each filteredColors as color (color.id)}
					{@render colorRow(color, false)}
				{/each}
			</div>
			{#if filteredColors.length === 0}
				<p class="py-4 text-center text-sm text-text-muted">No colors match “{search}”.</p>
			{/if}
		</div>
	</div>

	<!-- How-to for labelers -->
	<div class="mt-8 border border-border bg-surface p-5">
		<h2 class="mb-3 text-2xl font-bold text-text">Directions</h2>
		<ul class="flex flex-col gap-2 text-sm text-text">
			<li class="flex gap-2">
				<span class="shrink-0 text-primary">→</span>
				<span>Use the crop images from <span class="font-medium">both channels</span> to judge the piece's true color.</span>
			</li>
			<li class="flex gap-2">
				<span class="shrink-0 text-primary">→</span>
				<span>Pick the correct color from the sidebar. If you can tell it, that's enough — you can skip the same-piece step.</span>
			</li>
			<li class="flex gap-2">
				<span class="shrink-0 text-primary">→</span>
				<span>Under <span class="font-medium">Same piece across channels</span>, keep or add the upstream crops that show this same physical piece. Don't bother if you can already see the whole piece in its own bbox.</span>
			</li>
			<li class="flex gap-2">
				<span class="shrink-0 text-primary">→</span>
				<span>Try to do <span class="font-medium">both</span> for each piece. If one has incomplete info — you can't tell the color, or can't find the piece in the earlier pictures — just do the half you're sure of and hit <span class="font-medium">Continue</span>.</span>
			</li>
		</ul>
	</div>

{/if}
