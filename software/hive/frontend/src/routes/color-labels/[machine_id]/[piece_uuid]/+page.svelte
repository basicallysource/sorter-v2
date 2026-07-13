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
	import Sparkles from 'lucide-svelte/icons/sparkles';

	const SIMILAR_COUNT = 10;
	const ZONE_LABEL: Record<number, string> = { 0: 'mid', 1: 'drop', 2: 'exit', 3: 'precise' };

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
	let cropSaved = $state(false);
	let cropError = $state<string | null>(null);

	const guessColorId = $derived.by(() => {
		const id = detail?.pixel_guess?.color_id;
		return id != null && colorsById.has(id) ? id : null;
	});

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

	const similarColors = $derived.by(() => {
		const target = hexToLab(detail?.pixel_guess?.rgb ?? null);
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
		void goto(`/color-labels/${k.machine_id}/${encodeURIComponent(k.piece_uuid)}`);
	}

	async function goNext() {
		const next = await nav.nextAfter({ machine_id: machineId, piece_uuid: pieceUuid });
		if (next) gotoKey(next);
		else void goto('/color-labels');
	}

	async function goPrev() {
		const prev = await nav.prevBefore({ machine_id: machineId, piece_uuid: pieceUuid });
		if (prev) gotoKey(prev);
		else void goto('/color-labels');
	}

	async function saveColor(colorId: number, advance: boolean) {
		if (submitting) return;
		submitting = true;
		error = null;
		try {
			await api.submitColorLabel({ machine_id: machineId, piece_uuid: pieceUuid, color_id: colorId });
			myColorId = colorId;
			search = '';
			if (advance) await goNext();
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
		cropSaved = false;
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
		} catch (e: unknown) {
			cropError = errMsg(e, 'Failed to save selection');
		} finally {
			cropSaving = false;
		}
	}

	function onKey(e: KeyboardEvent) {
		if (e.target instanceof HTMLInputElement) return;
		if (e.key === 'Enter') {
			e.preventDefault();
			if (guessColorId == null) return;
			if (e.ctrlKey || e.metaKey) void saveCrops(); // accept same-piece selection
			else if (e.shiftKey) void saveColor(guessColorId, false); // accept color, stay
			else void saveColor(guessColorId, true); // accept color, move on
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
	<a href="/color-labels" class="flex items-center gap-1 text-sm text-text-muted hover:text-text">
		<ArrowLeft size={14} /> All pieces
	</a>
	{#if pos.total > 0 && pos.index >= 0}
		<span class="text-xs text-text-muted tabular-nums">{pos.index + 1} of {pos.total}{pos.hasMore ? '+' : ''}</span>
	{/if}
</div>

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
	<div class="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
		<!-- Piece under review -->
		<div class="border border-border bg-surface p-4 lg:col-start-1 lg:row-start-1">
			<div class="mb-3 flex flex-wrap items-center gap-2">
				<span class="text-sm font-medium text-text">
					{detail.part.part_name || detail.part.part_id || 'Unidentified'}
				</span>
				{#if detail.part.part_id}
					<span class="text-xs text-text-muted">#{detail.part.part_id}</span>
				{/if}
				<span class="text-xs text-text-muted">· {detail.machine_name ?? 'machine'}</span>
				{#if myColorId != null}
					{@const mc = colorsById.get(myColorId)}
					<span class="ml-auto flex items-center gap-1 text-xs text-success">
						<span class="inline-block h-3 w-3 border border-border" style={`background:#${mc?.rgb ?? '000'}`}></span>
						labeled {mc?.name ?? myColorId}
					</span>
				{/if}
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
						<div class="uppercase tracking-wide text-[10px]">Pixel-average guess</div>
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

		<!-- Same physical piece across the upstream channels (independent save) -->
		<div class="border border-border bg-surface p-4 lg:col-start-1 lg:row-start-2">
			<div class="mb-1 flex flex-wrap items-center justify-between gap-2">
				<span class="text-sm font-medium text-text">Same piece across channels</span>
				<div class="flex items-center gap-2">
					{#if cropSaved}
						<span class="text-xs text-success">Saved</span>
					{/if}
					<span class="text-xs text-text-muted tabular-nums">
						{cropSelected.size} of {cropCandidates.length} selected
					</span>
					<Button
						variant="primary"
						size="sm"
						loading={cropSaving}
						disabled={cropCandidates.length === 0 || cropLoading}
						onclick={saveCrops}
					>
						Accept selection
					</Button>
				</div>
			</div>
			<p class="mb-3 text-sm text-text-muted">
				Our guess of which upstream C2/C3 crops are this same physical piece, ranked by a
				time-and-angle heuristic. Keep or drop our picks and add any we missed, then
				<span class="font-medium">Accept</span> (Ctrl/⌘+Enter) — saved separately from the color.
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

		<!-- Palette picker -->
		<div class="flex flex-col border border-border bg-surface p-4 lg:col-start-2 lg:row-start-1 lg:row-span-2">
			<div class="mb-3 flex items-center justify-between">
				<span class="text-sm font-medium text-text">True color</span>
				<div class="flex gap-1.5">
					<Button variant="ghost" size="sm" onclick={goPrev}><ArrowLeft size={14} /> Back</Button>
					<Button variant="secondary" size="sm" onclick={goNext} disabled={submitting}>Skip <ArrowRight size={14} /></Button>
				</div>
			</div>

			{#if guessColorId != null}
				{@const gc = colorsById.get(guessColorId)}
				<button
					class="mb-3 flex items-center gap-2 border border-success/60 bg-success/8 px-3 py-2 text-sm text-text hover:bg-success/15 disabled:opacity-50"
					onclick={() => saveColor(guessColorId!, true)}
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
					myColorId
						? 'border-success'
						: color.id === guessColorId
							? 'border-info'
							: 'border-border'}"
					title={`${color.name} (${color.id})`}
					onclick={() => saveColor(color.id, true)}
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

			<div class="grid max-h-[52vh] grid-cols-4 gap-1.5 overflow-y-auto pr-1">
				{#each filteredColors as color (color.id)}
					{@render swatch(color)}
				{/each}
			</div>
			{#if filteredColors.length === 0}
				<p class="py-4 text-center text-xs text-text-muted">No colors match “{search}”.</p>
			{/if}
		</div>
	</div>

	<div class="mt-3 flex flex-wrap items-center gap-3 text-xs text-text-muted">
		{#if submitting}<Spinner />{/if}
		<span>
			Keys: <span class="text-text">Enter</span> save color + next ·
			<span class="text-text">Shift+Enter</span> save color, stay ·
			<span class="text-text">Ctrl/⌘+Enter</span> accept same-piece ·
			<span class="text-text">→</span>/<span class="text-text">Space</span> skip ·
			<span class="text-text">←</span> back
		</span>
	</div>
{/if}
