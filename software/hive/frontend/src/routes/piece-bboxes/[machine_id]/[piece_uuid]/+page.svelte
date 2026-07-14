<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		type BrickLinkColor,
		type ColorLabelCorrection,
		type ColorLabelPieceDetail,
		type PossibleCropCandidate
	} from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import * as nav from '$lib/colorLabelNav';
	import MachineLabeledPieces from '$lib/components/MachineLabeledPieces.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import ZoomImage from '$lib/components/ZoomImage.svelte';
	import { Alert, Button } from '$lib/components/primitives';
	import ArrowLeft from 'lucide-svelte/icons/arrow-left';
	import ArrowRight from 'lucide-svelte/icons/arrow-right';
	import Ban from 'lucide-svelte/icons/ban';
	import Check from 'lucide-svelte/icons/check';
	import ChevronDown from 'lucide-svelte/icons/chevron-down';
	import Circle from 'lucide-svelte/icons/circle';
	import CircleCheck from 'lucide-svelte/icons/circle-check';
	import CircleDot from 'lucide-svelte/icons/circle-dot';
	import Sparkles from 'lucide-svelte/icons/sparkles';

	type CharState = 'empty' | 'progress' | 'ready';

	const REJECT_REASONS: { value: string; label: string }[] = [
		{ value: 'no_piece', label: 'No piece in the frame' },
		{ value: 'multiple_pieces', label: 'Multiple pieces in the frame' }
	];

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
	let cantTell = $state(false); // saved "I can't tell" answer for THIS piece
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
	// Which source drove the pre-selection: the time/angle heuristic, the active
	// link matcher model, or a stored vision-model (AI) prediction. The AI "Run"
	// action is open to admins or anyone with their own OpenRouter key on file.
	let predictionSource = $state<'ai' | 'model' | 'heuristic'>('heuristic');
	let linkModel = $state<string | null>(null); // active link model name when source === 'model'
	let aiReasoning = $state<string | null>(null);
	let aiRunning = $state(false);
	const canRunAi = $derived(auth.isAdmin || auth.user?.openrouter_configured === true);

	// Reject-this-bbox-sample
	let rejectOpen = $state(false);
	let rejecting = $state(false);
	let rejectReasons = $state<Set<string>>(new Set());
	let rejected = $state(false); // this user already rejected the piece

	// Brickognize part/color correction feedback
	let correction = $state<ColorLabelCorrection | null>(null);
	let partVerdict = $state<boolean | null>(null); // pending part right/wrong choice
	let sendingFeedback = $state(false);
	// Result banner after a send: success (reached Brickognize), warning (saved
	// but Brickognize didn't accept it), or danger (the request itself failed).
	let feedback = $state<{ variant: 'success' | 'warning' | 'danger'; text: string } | null>(null);

	// The suggestion that seeds the picker: prefer the active color model's
	// prediction, fall back to the pixel-average guess. Both are still shown in
	// the piece panel; this just drives which one highlights in the color list.
	const suggestion = $derived.by(() => {
		const mp = detail?.model_prediction;
		if (mp) return { color_id: mp.color_id, rgb: mp.rgb };
		const pg = detail?.pixel_guess;
		if (pg) return { color_id: pg.color_id, rgb: pg.rgb };
		return null;
	});

	const guessColorId = $derived.by(() => {
		const id = suggestion?.color_id;
		return id != null && colorsById.has(id) ? id : null;
	});

	// --- Per-characteristic completion state (extensible) ---------------------
	const colorState = $derived<CharState>(myColorId != null || cantTell ? 'ready' : 'empty');
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
		// An "I can't tell" color isn't something to "accept" — just move on.
		if (cantTell && touched.length === 1 && touched[0].key === 'color') return 'Move on';
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
		const target = hexToLab(suggestion?.rgb ?? null);
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
			cantTell = d.my_label?.cant_tell ?? false;
			rejectOpen = false;
			rejected = d.my_rejection != null;
			rejectReasons = new Set(d.my_rejection?.reasons ?? []);
			correction = d.correction;
			partVerdict = d.correction.part_correct;
			feedback = null;
			applyCrops(crops);
			pos = nav.position({ machine_id: mid, piece_uuid: puid });
		} catch (e: unknown) {
			if (pieceKey === k) error = errMsg(e, 'Failed to load piece');
		} finally {
			if (pieceKey === k) loading = false;
		}
	}

	// Whether a candidate is the active source's pre-selected pick: the AI's
	// verdict, the link model's pick, or the time/angle heuristic's flag.
	function isPredictionPick(
		c: import('$lib/api').PossibleCropCandidate,
		source: 'ai' | 'model' | 'heuristic'
	): boolean {
		if (source === 'ai') return c.ai_same === true;
		if (source === 'model') return c.model_same === true;
		return c.predicted;
	}

	const SOURCE_PICK_LABEL = { ai: 'AI', model: 'model', heuristic: 'heuristic' } as const;

	// Load a possible-crops result into state. If the user already saved a
	// selection, restore it; otherwise pre-select the active source's picks — the
	// AI's stored prediction, else the link model's scores, else the heuristic.
	function applyCrops(crops: import('$lib/api').PossibleCropsResult, preferAi = false) {
		cropCandidates = crops.candidates;
		cropArrivalTs = crops.arrival_ts;
		cropDirty = false;
		predictionSource = crops.prediction_source;
		linkModel = crops.link_model;
		aiReasoning = crops.ai_reasoning;
		const savedPos = crops.my_link.filter((m) => m.is_same).map((m) => m.local_id);
		// A just-run AI prediction overrides the saved selection in the UI so the
		// labeler can review the fresh picks; on plain load, a saved selection wins.
		if (crops.my_link.length > 0 && !preferAi) {
			const present = new Set(crops.candidates.map((c) => c.local_id));
			cropSelected = new Set(savedPos.filter((id) => present.has(id)));
			cropSaved = true;
		} else {
			const source = preferAi ? 'ai' : crops.prediction_source;
			cropSelected = new Set(
				crops.candidates.filter((c) => isPredictionPick(c, source)).map((c) => c.local_id)
			);
			cropSaved = crops.my_link.length > 0;
		}
	}

	async function runAiPredict() {
		if (aiRunning || cropCandidates.length === 0) return;
		aiRunning = true;
		cropError = null;
		try {
			const crops = await api.runAiPredict(machineId, pieceUuid);
			applyCrops(crops, true);
			cropDirty = true; // AI picks are a fresh suggestion; prompt a save
		} catch (e: unknown) {
			cropError = errMsg(e, 'AI prediction failed');
		} finally {
			aiRunning = false;
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
			cantTell = false;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to save color');
		} finally {
			submitting = false;
		}
	}

	// "I can't tell" — a real answer (color is indeterminate), saved like a color
	// pick. Clears any concrete color for this piece.
	async function pickCantTell() {
		if (submitting) return;
		if (cantTell) {
			// Toggle off: remove the answer entirely.
			await clearColorAnswer();
			return;
		}
		submitting = true;
		error = null;
		try {
			await api.submitColorLabel({ machine_id: machineId, piece_uuid: pieceUuid, cant_tell: true });
			cantTell = true;
			myColorId = null;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to save');
		} finally {
			submitting = false;
		}
	}

	async function clearColorAnswer() {
		if (submitting) return;
		submitting = true;
		error = null;
		try {
			if (myColorId != null || cantTell) await api.deleteColorLabel(machineId, pieceUuid);
			myColorId = null;
			cantTell = false;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to clear');
		} finally {
			submitting = false;
		}
	}

	// Skip: discard whatever was recorded for this piece (a skip almost always
	// means the earlier input was a mistake) and move on without saving.
	async function skipAndReset() {
		if (myColorId != null || cantTell) {
			try {
				await api.deleteColorLabel(machineId, pieceUuid);
			} catch {
				/* already gone */
			}
		}
		if (cropSaved) {
			try {
				await api.deletePieceCropLink(machineId, pieceUuid);
			} catch {
				/* already gone */
			}
		}
		myColorId = null;
		cantTell = false;
		cropSelected = new Set();
		cropSaved = false;
		cropDirty = false;
		await goNext();
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

	// When the labeler's true color disagrees with Brickognize's own color guess,
	// quietly send a "color incorrect" correction to Brickognize. Fire-and-forget:
	// the server records it regardless of the network result, and we're leaving the
	// piece. We never surface Brickognize's predicted color in the UI — this just
	// compares against it under the hood. Skips when it agrees (don't spam) or when
	// Brickognize had no color to contradict.
	function autoSubmitColorDisagreement() {
		if (!correction?.correctable || correction.color_feedback_submitted) return;
		if (myColorId == null) return;
		const predicted = detail?.prediction.color_id;
		if (predicted == null || String(myColorId) === String(predicted)) return;
		void api.submitBrickognizeFeedback(machineId, pieceUuid, { color_corrected_id: myColorId });
	}

	// The summary action: commit anything still in progress, then move on.
	async function commitAndAdvance() {
		if (cropDirty) await saveCrops();
		autoSubmitColorDisagreement();
		await goNext();
	}

	function toggleReason(reason: string) {
		const s = new Set(rejectReasons);
		if (s.has(reason)) s.delete(reason);
		else s.add(reason);
		rejectReasons = s;
	}

	// Reject the bbox sample with the chosen reason(s), then move on.
	async function submitReject() {
		if (rejecting || rejectReasons.size === 0) return;
		rejecting = true;
		error = null;
		try {
			await api.savePieceRejection({
				machine_id: machineId,
				piece_uuid: pieceUuid,
				reasons: [...rejectReasons]
			});
			rejected = true;
			rejectOpen = false;
			await goNext();
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to reject piece');
		} finally {
			rejecting = false;
		}
	}

	// Send the PART verdict to Brickognize. (Color feedback is handled
	// automatically on advance — see autoSubmitColorDisagreement — and its
	// prediction is never shown here.)
	async function sendBrickognizeFeedback() {
		if (sendingFeedback || !correction) return;
		sendingFeedback = true;
		feedback = null;
		try {
			const body: { part_correct?: boolean | null } = {};
			if (!correction.part_feedback_submitted && partVerdict != null) {
				body.part_correct = partVerdict;
			}
			const res = await api.submitBrickognizeFeedback(machineId, pieceUuid, body);
			correction = res.correction;
			partVerdict = res.correction.part_correct;
			if (res.submit_error) {
				feedback = {
					variant: 'warning',
					text: `Saved, but Brickognize didn't accept it: ${res.submit_error}`
				};
			} else if (res.part_submitted) {
				feedback = { variant: 'success', text: 'Sent to Brickognize.' };
			} else {
				feedback = { variant: 'success', text: 'Saved.' };
			}
		} catch (e: unknown) {
			feedback = { variant: 'danger', text: errMsg(e, 'Failed to send correction') };
		} finally {
			sendingFeedback = false;
		}
	}

	function onKey(e: KeyboardEvent) {
		if (e.target instanceof HTMLInputElement) return;
		if (e.key === 'Enter') {
			e.preventDefault();
			void commitAndAdvance();
		} else if (e.key === 'ArrowRight' || e.key === ' ') {
			e.preventDefault();
			void skipAndReset();
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
			<span class="hidden text-xs text-text-muted md:inline">Enter accept · →/Space skip · ← back</span>
			<!-- Reject this bbox sample (with reason(s)) — left of the skip/continue CTA -->
			<div class="relative">
				<Button
					variant={rejected ? 'danger' : 'secondary'}
					size="sm"
					onclick={() => (rejectOpen = !rejectOpen)}
				>
					<Ban size={14} /> {rejected ? 'Rejected' : 'Reject'} <ChevronDown size={13} />
				</Button>
				{#if rejectOpen}
					<div class="absolute right-0 z-30 mt-1 w-64 border border-border bg-surface p-2 shadow-lg">
						<div class="mb-1 px-1 text-xs font-semibold uppercase tracking-wider text-text-muted">
							Reject sample — why?
						</div>
						{#each REJECT_REASONS as r (r.value)}
							<label class="flex cursor-pointer items-center gap-2 px-1 py-1 text-sm text-text hover:bg-bg">
								<input
									type="checkbox"
									checked={rejectReasons.has(r.value)}
									onchange={() => toggleReason(r.value)}
								/>
								{r.label}
							</label>
						{/each}
						<div class="mt-2 flex justify-end">
							<Button
								variant="danger"
								size="sm"
								loading={rejecting}
								disabled={rejectReasons.size === 0}
								onclick={submitReject}
							>
								Reject &amp; next
							</Button>
						</div>
					</div>
				{/if}
			</div>
			<!-- Skip is always available; skipping resets whatever was recorded for
			     this piece (see skipAndReset). Accept/Continue appears once the
			     labeler has actually entered something. -->
			<Button variant="ghost" size="sm" onclick={skipAndReset}>Skip</Button>
			{#if touched.length > 0}
				<Button variant="primary" size="sm" loading={cropSaving} onclick={commitAndAdvance}>
					{ctaLabel} <ArrowRight size={14} />
				</Button>
			{/if}
		</div>
	</div>

	<div class="flex flex-col gap-6 lg:flex-row lg:items-start">
		<!-- Reference column: this machine's already-labeled colors (ground truth) -->
		<aside class="shrink-0 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:w-52 lg:overflow-y-auto">
			<MachineLabeledPieces {machineId} {pieceUuid} />
		</aside>

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
					<ZoomImage
						src={api.colorLabelImageUrl(machineId, pieceUuid, img.seq)}
						alt={`crop ${img.seq}`}
						title={`seq ${img.seq}${img.source ? ` · ${img.source}` : ''}`}
						class="h-28 w-28 border-2 bg-transparent object-contain {img.used ? 'border-success' : 'border-border'}"
					/>
				{/each}
			</div>

			<div class="mt-4 flex flex-col gap-3 border-t border-border pt-3">
				<!-- Model prediction (primary, when a color model is active) -->
				{#if detail.model_prediction}
					{@const mp = detail.model_prediction}
					<div class="flex items-center gap-3">
						<span
							class="h-10 w-10 shrink-0 border border-border"
							style={`background:#${mp.rgb ?? '888888'}`}
							title={`model color #${mp.rgb ?? '?'}`}
						></span>
						<div class="min-w-0 text-xs text-text-muted">
							<div class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider">
								<Sparkles size={12} class="text-info" /> Model prediction
								<span class="font-normal normal-case text-text-muted">· {mp.model_name}</span>
							</div>
							<div class="mt-0.5 flex items-center gap-1.5">
								<span class="text-text">{mp.color_name ?? mp.color_id}</span>
								<span>({mp.color_id})</span>
								<span class="ml-2">{Math.round(mp.confidence * 100)}% · {mp.sample_count} crop{mp.sample_count === 1 ? '' : 's'}</span>
							</div>
						</div>
					</div>
				{/if}

				<!-- Pixel-average guess (secondary reference when a model is active) -->
				{#if detail.pixel_guess}
					<div class="flex items-center gap-3 {detail.model_prediction ? 'opacity-70' : ''}">
						<span
							class="h-10 w-10 shrink-0 border border-border"
							style={`background:#${detail.pixel_guess.rgb}`}
							title={`average pixel color #${detail.pixel_guess.rgb}`}
						></span>
						<div class="min-w-0 text-xs text-text-muted">
							<div class="text-xs font-semibold uppercase tracking-wider">Pixel-average guess</div>
							<div class="mt-0.5 flex items-center gap-1.5">
								{#if detail.pixel_guess.color_id != null && colorsById.has(detail.pixel_guess.color_id)}
									{@const pc = colorsById.get(detail.pixel_guess.color_id)}
									<span class="inline-block h-3.5 w-3.5 border border-border" style={`background:#${pc?.rgb ?? '000'}`}></span>
								{/if}
								<span class="text-text">{detail.pixel_guess.color_name}</span>
								<span>({detail.pixel_guess.color_id})</span>
								<span class="ml-2">nearest of {detail.pixel_guess.sample_count} crop{detail.pixel_guess.sample_count === 1 ? '' : 's'}</span>
							</div>
						</div>
					</div>
				{/if}

				{#if !detail.model_prediction && !detail.pixel_guess}
					<span class="text-xs text-text-muted">No suggestion — crops unavailable.</span>
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
					{#if canRunAi}
						<Button
							variant="secondary"
							size="sm"
							loading={aiRunning}
							disabled={cropCandidates.length === 0 || cropLoading}
							onclick={runAiPredict}
						>
							<span class="flex items-center gap-1"><Sparkles size={13} /> Run AI</span>
						</Button>
					{/if}
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
			<p class="mb-2 text-sm text-text-muted">
				Our guess of which upstream C2/C3 crops are this same physical piece. Keep or drop
				the picks and add any we missed, then <span class="font-medium">Accept</span>.
			</p>
			<p class="mb-3 flex items-center gap-1.5 text-xs">
				{#if predictionSource === 'ai'}
					<Sparkles size={12} class="shrink-0 text-info" />
					<span class="text-text-muted">
						Picks from a vision model{aiReasoning ? `: ${aiReasoning}` : '.'}
					</span>
				{:else if predictionSource === 'model'}
					<Sparkles size={12} class="shrink-0 text-info" />
					<span class="text-text-muted">
						Picks from the link matcher model{linkModel ? ` (${linkModel})` : ''}.{canRunAi ? ' Run AI for a vision-model guess.' : ''}
					</span>
				{:else}
					<span class="text-text-muted">
						Picks from the time-and-angle heuristic.{canRunAi ? ' Run AI for a vision-model guess.' : ''}
					</span>
				{/if}
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
						{@const isPick = isPredictionPick(c, predictionSource)}
						<button
							type="button"
							onclick={() => toggleCrop(c.local_id)}
							title={`C${c.channel} · ${ZONE_LABEL[c.zone_code ?? 0] ?? '?'} · ${c.dt != null ? c.dt + 's before arrival' : 'unknown dt'} · ${c.com_forward_to_exit_deg != null ? Math.round(c.com_forward_to_exit_deg) + '° to exit' : ''} · score ${c.score}${predictionSource === 'model' && c.model_score != null ? ` · model ${c.model_score}` : ''}${isPick ? ` · ${SOURCE_PICK_LABEL[predictionSource]} pick` : ''}`}
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
							{#if isPick}
								<span
									class="absolute right-0.5 top-0.5 flex items-center bg-info/80 p-0.5 text-white"
									title={`${SOURCE_PICK_LABEL[predictionSource]} prediction`}
								>
									<Sparkles size={11} />
								</span>
							{/if}
						</button>
					{/each}
				</div>
			{/if}
			</div>
		</div>

		<!-- Sidebar: color picker + Brickognize correction. Sticky, capped to the
		     viewport; the color list fills the space and scrolls internally so the
		     Brickognize box below always stays on-screen. -->
		<div class="flex flex-col gap-6 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:w-96">
		<!-- Color picker -->
		<div class="flex min-h-0 flex-1 flex-col border bg-surface p-4 {stateBorder(colorState)}">
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

			<!-- "I can't tell" — an explicit indeterminate-color answer -->
			<button
				class="mb-3 flex items-center gap-2 border px-2 py-1 text-left text-sm hover:border-primary disabled:opacity-50 {cantTell
					? 'border-success bg-success/10 text-text'
					: 'border-border text-text-muted'}"
				onclick={pickCantTell}
				disabled={submitting}
			>
				<Ban size={14} class="shrink-0 {cantTell ? 'text-success' : 'text-text-muted'}" />
				<span class="flex-1">I can't tell the color</span>
				{#if cantTell}<Check size={14} class="shrink-0 text-success" />{/if}
			</button>

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

			<div class="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto pr-1">
				{#each filteredColors as color (color.id)}
					{@render colorRow(color, false)}
				{/each}
			</div>
			{#if filteredColors.length === 0}
				<p class="py-4 text-center text-sm text-text-muted">No colors match “{search}”.</p>
			{/if}
		</div>

		<!-- Brickognize part correction — only when the piece has a Brickognize
		     listing. Color feedback is sent automatically on advance when the
		     labeler's true color disagrees with Brickognize's (its predicted color
		     is intentionally not shown). -->
		{#if correction?.correctable}
			{@const partSent = correction.part_feedback_submitted}
			{@const canSendPart = !partSent && partVerdict != null}
			<div class="flex shrink-0 flex-col border border-border bg-surface p-4">
				<div class="mb-3 flex items-center justify-between gap-2">
					<span class="text-sm font-medium text-text">Is this the right part?</span>
					{#if partSent}
						<span class="flex items-center gap-1 text-xs text-success"><CircleCheck size={13} /> Sent</span>
					{/if}
				</div>

				<!-- Predicted part + verdict -->
				<div class="mb-2 flex items-center gap-2 text-sm text-text">
					<span class="truncate">{detail.part.part_name || detail.part.part_id || 'Unidentified'}</span>
					{#if detail.part.part_id}
						<span class="text-xs text-text-muted">#{detail.part.part_id}</span>
					{/if}
				</div>

				<div class="mb-3 flex items-center gap-2">
					<Button
						variant={partVerdict === true ? 'primary' : 'secondary'}
						size="sm"
						disabled={partSent}
						onclick={() => (partVerdict = true)}
					>
						<Check size={14} /> Correct
					</Button>
					<Button
						variant={partVerdict === false ? 'danger' : 'secondary'}
						size="sm"
						disabled={partSent}
						onclick={() => (partVerdict = false)}
					>
						<Ban size={14} /> Wrong
					</Button>
					{#if partSent}
						<span class="ml-auto flex items-center gap-1 text-xs text-success" title="already sent to Brickognize">
							<CircleCheck size={13} /> sent
						</span>
					{/if}
				</div>

				{#if feedback}
					<div class="mb-2">
						<Alert variant={feedback.variant}>{feedback.text}</Alert>
					</div>
				{/if}

				<Button
					variant="primary"
					size="sm"
					loading={sendingFeedback}
					disabled={!canSendPart}
					onclick={sendBrickognizeFeedback}
				>
					{#if partSent}
						Sent to Brickognize
					{:else}
						Send to Brickognize
					{/if}
				</Button>
			</div>
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
