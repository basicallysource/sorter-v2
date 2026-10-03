<script module lang="ts">
	// What the panel reports back to a host list so the card/row can update its
	// "you labeled this" indicators without a full refetch.
	export type PieceLabelPatch = { my_color: boolean; my_crop: boolean };
</script>

<script lang="ts">
	import {
		api,
		IMAGE_QUALITY_REASONS,
		type BrickLinkColor,
		type ColorLabelCorrection,
		type ColorLabelPieceDetail,
		type ImageQualityFlags,
		type ImageQualityReason,
		type PartBrickLinkColor,
		type PartSummary,
		type PossibleCropCandidate
	} from '$lib/api';
	import { hexToLab, isExoticFinish, labDistance } from '$lib/colorLab';
	import { auth } from '$lib/auth.svelte';
	import * as nav from '$lib/colorLabelNav';
	import MachineLabeledPieces from '$lib/components/MachineLabeledPieces.svelte';
	import PartBrickLinkColors from '$lib/components/PartBrickLinkColors.svelte';
	import PiecePartPicker from '$lib/components/PiecePartPicker.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import ZoomImage from '$lib/components/ZoomImage.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Checkbox from '$lib/components/Checkbox.svelte';
	import Input from '$lib/components/Input.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Popover from '$lib/components/Popover.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Button from '$lib/components/Button.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Ban from '@lucide/svelte/icons/ban';
	import Check from '@lucide/svelte/icons/check';
	import Flag from '@lucide/svelte/icons/flag';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import Star from '@lucide/svelte/icons/star';
	import X from '@lucide/svelte/icons/x';

	type CharState = 'empty' | 'progress' | 'ready';

	type Props = {
		machineId: string;
		pieceUuid: string;
		// 'page' is the standalone full-width labeling route; 'pane' is the compact
		// stacked layout used inside the list page's split view.
		layout?: 'page' | 'pane';
		position?: { index: number; total: number; hasMore: boolean };
		onNext: () => void | Promise<void>;
		onPrev: () => void | Promise<void>;
		// Present in pane mode — renders a close control instead of the back-to-list link.
		onClose?: () => void;
		onChange?: (key: nav.PieceKey, patch: PieceLabelPatch) => void;
	};

	let {
		machineId,
		pieceUuid,
		layout = 'page',
		position = { index: -1, total: 0, hasMore: true },
		onNext,
		onPrev,
		onClose,
		onChange
	}: Props = $props();

	// Attribute codes a labeler can flag on the sample. All of these currently
	// count as rejects (the piece drops from the queue), but they're modeled as
	// attributes on the piece — "assembly" (parts built into one unit) and
	// "pieces_entangled" (separate parts stuck together) are kept, not deleted.
	const REJECT_REASONS: { value: string; label: string }[] = [
		{ value: 'no_piece', label: 'No piece in the frame' },
		{ value: 'multiple_pieces', label: 'Multiple pieces in the frame' },
		{ value: 'not_lego', label: 'Not a real Lego piece' },
		{ value: 'assembly', label: 'Assembly (parts built together)' },
		{ value: 'pieces_entangled', label: 'Pieces entangled' }
	];

	const SIMILAR_COUNT = 8;
	const ZONE_LABEL: Record<number, string> = { 0: 'mid', 1: 'drop', 2: 'exit', 3: 'precise' };

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

	// Part (mold) correction — this user's answer for THIS piece, restored on load
	let myPart = $state<PartSummary | null>(null);
	let partCantTell = $state(false);
	let partSaving = $state(false);

	// Reject-this-bbox-sample
	let rejectOpen = $state(false);
	let rejecting = $state(false);
	let rejectReasons = $state<Set<string>>(new Set());
	let rejected = $state(false); // this user already rejected the piece

	// Per-image quality (star + "not good enough" reasons), saved per crop. One
	// reasons dropdown open at a time, keyed `${kind}:${id}`; positioned fixed so
	// it escapes the candidate grid's overflow clipping.
	let qualitySavingFor = $state<string | null>(null);

	// Brickognize part/color correction feedback
	let correction = $state<ColorLabelCorrection | null>(null);
	let partVerdict = $state<boolean | null>(null); // pending part right/wrong choice
	let sendingFeedback = $state(false);
	// Result banner after a send: success (reached Brickognize), warning (saved
	// but Brickognize didn't accept it), or danger (the request itself failed).
	let feedback = $state<{ variant: 'success' | 'warning' | 'danger'; text: string } | null>(null);

	// Report the current "mine" flags up to the host list so the card reflects
	// that this user has labeled the piece, without waiting for a refetch.
	function notifyChange() {
		onChange?.(
			{ machine_id: machineId, piece_uuid: pieceUuid },
			{ my_color: myColorId != null || cantTell, my_crop: cropSaved }
		);
	}

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
	const partState = $derived<CharState>(myPart != null || partCantTell ? 'ready' : 'empty');
	// Add future piece characteristics here; the summary bar + CTA derive from it.
	const characteristics = $derived([
		{ key: 'part', label: 'Part', state: partState },
		{ key: 'color', label: 'Color', state: colorState },
		{ key: 'pieces', label: 'Same piece', state: piecesState }
	]);
	const touched = $derived(characteristics.filter((c) => c.state !== 'empty'));
	// An "I can't tell" isn't something to "accept" — if that's the only thing
	// recorded, the CTA is just "move on".
	const onlyCantTells = $derived(
		touched.length > 0 &&
			touched.every(
				(c) =>
					(c.key === 'color' && cantTell) || (c.key === 'part' && partCantTell && myPart == null)
			)
	);
	const ctaLabel = $derived.by(() => {
		if (touched.length === 0) return 'Skip';
		if (touched.length === characteristics.length) return 'Continue';
		if (onlyCantTells) return 'Move on';
		return 'Accept ' + touched.map((c) => c.label.toLowerCase()).join(' + ');
	});

	const filteredColors = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (!q) return colors;
		return colors.filter((c) => c.name.toLowerCase().includes(q) || String(c.id) === q);
	});

	const labById = $derived(new Map(colors.map((c) => [c.id, hexToLab(c.rgb)] as const)));

	// BrickLink for-sale mix for this part. Owned here rather than in the sidebar
	// because the numbers matter most next to the colors you're choosing between.
	let blItems = $state<PartBrickLinkColor[]>([]);
	let blItemNo = $state<string | null>(null);
	let blUpdatedAt = $state<string | null>(null);
	let blLoading = $state(false);
	let blError = $state<string | null>(null);
	let blSource = $state<'live' | 'cache'>('cache');

	async function loadBrickLink(partId: string) {
		blLoading = true;
		blError = null;
		try {
			const res = await api.partBrickLinkColors(partId, 250);
			blItems = res.items;
			blItemNo = res.item_no;
			blUpdatedAt = res.updated_at;
			blSource = res.source;
		} catch {
			blError = 'Failed to load';
		} finally {
			blLoading = false;
		}
	}

	$effect(() => {
		// A human part correction wins over the machine's guess — it's better
		// ground truth, and for an unidentified piece it's the only thing that can
		// populate this column at all. Re-runs when the correction changes.
		const partId = myPart?.part_num ?? detail?.part.part_id ?? null;
		if (!partId) {
			blItems = [];
			blItemNo = null;
			return;
		}
		void loadBrickLink(partId);
	});

	function isExotic(c: BrickLinkColor): boolean {
		return isExoticFinish(c.name, c.is_trans);
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
				return { color: c, d: labDistance(lab, target) + (isExotic(c) ? 55 : 0) };
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
			if (pieceKey !== k) return; // props changed mid-load
			detail = d;
			myColorId = d.my_label?.color_id ?? null;
			cantTell = d.my_label?.cant_tell ?? false;
			myPart = d.my_part_label?.part ?? null;
			partCantTell = d.my_part_label?.cant_tell ?? false;
			rejectOpen = false;
			rejected = d.my_rejection != null;
			rejectReasons = new Set(d.my_rejection?.reasons ?? []);
			correction = d.correction;
			partVerdict = d.correction.part_correct;
			feedback = null;
			applyCrops(crops);
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

	async function goNext() {
		search = '';
		await onNext();
	}

	async function goPrev() {
		search = '';
		await onPrev();
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
			notifyChange();
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
			notifyChange();
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
			notifyChange();
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to clear');
		} finally {
			submitting = false;
		}
	}

	// --- Part (mold) correction -----------------------------------------------
	// Same contract as the color picker: every choice writes immediately, nothing
	// advances on its own. Picking a part that isn't the machine's guess is also
	// reported to Brickognize as a wrong-part verdict (see commitAndAdvance).

	async function pickPart(partNum: string) {
		if (partSaving) return;
		partSaving = true;
		error = null;
		try {
			const res = await api.submitPartLabel({
				machine_id: machineId,
				piece_uuid: pieceUuid,
				part_num: partNum
			});
			myPart = res.part;
			partCantTell = false;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to save part');
		} finally {
			partSaving = false;
		}
	}

	async function pickPartCantTell() {
		if (partSaving) return;
		if (partCantTell) {
			await clearPartAnswer();
			return;
		}
		partSaving = true;
		error = null;
		try {
			await api.submitPartLabel({
				machine_id: machineId,
				piece_uuid: pieceUuid,
				cant_tell: true
			});
			partCantTell = true;
			myPart = null;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to save');
		} finally {
			partSaving = false;
		}
	}

	async function clearPartAnswer() {
		if (partSaving) return;
		partSaving = true;
		error = null;
		try {
			if (myPart != null || partCantTell) await api.deletePartLabel(machineId, pieceUuid);
			myPart = null;
			partCantTell = false;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to clear');
		} finally {
			partSaving = false;
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
		if (myPart != null || partCantTell) {
			try {
				await api.deletePartLabel(machineId, pieceUuid);
			} catch {
				/* already gone */
			}
		}
		myColorId = null;
		cantTell = false;
		myPart = null;
		partCantTell = false;
		cropSelected = new Set();
		cropSaved = false;
		cropDirty = false;
		notifyChange();
		await goNext();
	}

	function toggleCrop(localId: number) {
		const s = new Set(cropSelected);
		if (s.has(localId)) s.delete(localId);
		else s.add(localId);
		cropSelected = s;
		cropDirty = true;
	}

	function selectNoCrops() {
		cropSelected = new Set();
		cropDirty = true;
	}

	// "None of these are the piece" — clearing the picks and committing in one
	// click. An empty selection is a real answer (the piece has no upstream
	// counterpart), not an un-answered state, so it still goes through saveCrops.
	async function rejectAllCrops() {
		selectNoCrops();
		await saveCrops();
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
			notifyChange();
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

	// Same idea for the mold: naming a different part than Brickognize did IS a
	// wrong-part verdict, so report it rather than making the labeler also click
	// through the "Is this the right part?" panel. Agreement is left to that
	// panel — auto-sending it would spam the feedback API with confirmations.
	function autoSubmitPartDisagreement() {
		if (!correction?.correctable || correction.part_feedback_submitted) return;
		if (myPart == null) return;
		const predicted = detail?.part.part_id;
		if (predicted == null || myPart.part_num === predicted) return;
		void api.submitBrickognizeFeedback(machineId, pieceUuid, { part_correct: false });
	}

	// The summary action: commit anything still in progress, then move on.
	async function commitAndAdvance() {
		if (cropDirty) await saveCrops();
		autoSubmitColorDisagreement();
		autoSubmitPartDisagreement();
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

	// --- Per-image quality flags ----------------------------------------------
	// Two independent controls on each crop: a "high quality" star and a
	// "not good enough for classification" reasons dropdown. Every toggle posts the
	// whole flag set for that crop; an all-false set clears the row server-side.
	function qualityBody(obj: ImageQualityFlags, kind: 'piece_image' | 'channel_crop', id: number) {
		const flags = {
			high_quality: obj.high_quality,
			low_resolution: obj.low_resolution,
			motion_blur: obj.motion_blur,
			not_contained: obj.not_contained,
			no_piece_in_frame: obj.no_piece_in_frame,
			other_bad: obj.other_bad
		};
		return kind === 'piece_image'
			? { machine_id: machineId, crop_kind: kind, piece_uuid: pieceUuid, seq: id, ...flags }
			: { machine_id: machineId, crop_kind: kind, crop_local_id: id, ...flags };
	}

	async function persistQuality(
		obj: ImageQualityFlags,
		kind: 'piece_image' | 'channel_crop',
		id: number,
		revert: () => void
	) {
		const key = `${kind}:${id}`;
		qualitySavingFor = key;
		try {
			await api.submitImageQuality(qualityBody(obj, kind, id));
		} catch (e: unknown) {
			revert();
			error = errMsg(e, 'Failed to save image quality');
		} finally {
			qualitySavingFor = null;
		}
	}

	async function toggleStar(obj: ImageQualityFlags, kind: 'piece_image' | 'channel_crop', id: number) {
		if (qualitySavingFor === `${kind}:${id}`) return;
		const prev = obj.high_quality;
		obj.high_quality = !prev;
		await persistQuality(obj, kind, id, () => {
			obj.high_quality = prev;
		});
	}

	async function toggleQualityReason(
		obj: ImageQualityFlags,
		kind: 'piece_image' | 'channel_crop',
		id: number,
		code: ImageQualityReason
	) {
		if (qualitySavingFor === `${kind}:${id}`) return;
		const prev = obj[code];
		obj[code] = !prev;
		await persistQuality(obj, kind, id, () => {
			obj[code] = prev;
		});
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
		// Keys inside an open popover (the reject and quality menus) are its own.
		if (e.target instanceof Element && e.target.closest('[popover]')) return;
		if (e.key === 'Enter') {
			e.preventDefault();
			void commitAndAdvance();
		} else if (e.key === 'ArrowRight' || e.key === ' ') {
			e.preventDefault();
			void skipAndReset();
		} else if (e.key === 'ArrowLeft') {
			e.preventDefault();
			void goPrev();
		} else if (e.key === 'Escape' && onClose) {
			e.preventDefault();
			onClose();
		}
	}

	// Reload whenever the target piece changes.
	$effect(() => {
		const mid = machineId;
		const puid = pieceUuid;
		if (!mid || !puid) return;
		void load(mid, puid, `${mid}|${puid}`);
	});
</script>

<svelte:window onkeydown={onKey} />

{#snippet statusBadge(state: CharState)}
	{#if state === 'ready'}
		<Badge tone="success" dot>Ready</Badge>
	{:else if state === 'progress'}
		<Badge tone="warning" dot>In progress</Badge>
	{:else}
		<Badge>Not started</Badge>
	{/if}
{/snippet}

<!-- Each crop's own quality: a high-quality star, and the reasons it is not good
     enough, saved per image. Over the tile, beside its button, not inside it. -->
{#snippet qualityOverlay(obj: ImageQualityFlags, kind: 'piece_image' | 'channel_crop', id: number)}
	{@const key = `${kind}:${id}`}
	{@const badCount = IMAGE_QUALITY_REASONS.filter((r) => obj[r.code]).length}
	<div class="absolute top-0.5 left-0.5 z-10 flex gap-0.5">
		<button
			type="button"
			title={obj.high_quality ? 'High quality; click to unset' : 'Mark as high quality'}
			aria-label="High quality"
			aria-pressed={obj.high_quality}
			onclick={() => toggleStar(obj, kind, id)}
			disabled={qualitySavingFor === key}
			class="flex rounded-badge bg-scrim p-0.5 disabled:opacity-45 {obj.high_quality ? 'text-warning' : 'text-white'}"
		>
			<Star size={14} fill={obj.high_quality ? 'currentColor' : 'none'} />
		</button>
		<Popover label="Why it is not good enough" width="15rem">
			{#snippet trigger(props)}
				<button
					{...props}
					type="button"
					title="Not good enough to classify"
					disabled={qualitySavingFor === key}
					class="flex items-center gap-0.5 rounded-badge bg-scrim p-0.5 disabled:opacity-45 {badCount > 0 ? 'text-danger' : 'text-white'}"
				>
					<Flag size={14} fill={badCount > 0 ? 'currentColor' : 'none'} />
					{#if badCount > 0}<span class="num text-xs leading-none">{badCount}</span>{/if}
				</button>
			{/snippet}
			<div class="label mb-2">Not good enough, because</div>
			<div class="flex flex-col gap-2">
				{#each IMAGE_QUALITY_REASONS as r (r.code)}
					<Checkbox checked={obj[r.code]} onchange={() => toggleQualityReason(obj, kind, id, r.code)}>{r.label}</Checkbox>
				{/each}
			</div>
		</Popover>
	</div>
{/snippet}

<!-- Back to the list (the page) or close (the pane), and where this piece is in it -->
{#snippet header()}
	<div class="flex items-center justify-between gap-3">
		{#if onClose}
			<Button size="sm" variant="ghost" icon={X} onclick={onClose}>Close</Button>
		{:else}
			<Button size="sm" variant="ghost" icon={ArrowLeft} href={nav.dashboardUrl()}>All pieces</Button>
		{/if}
		{#if position.total > 0 && position.index >= 0}
			<span class="num text-sm text-ink-muted">{position.index + 1} of {position.total}{position.hasMore ? '+' : ''}</span>
		{/if}
	</div>
{/snippet}

<!-- What is done across every characteristic, and the way on -->
{#snippet summaryBar()}
	<Panel flush>
		<div class="flex flex-wrap items-center gap-x-4 gap-y-2 px-(--pad-panel) py-3">
			<Button variant="ghost" size="sm" icon={ArrowLeft} onclick={goPrev}>Back</Button>
			<div class="flex flex-wrap items-center gap-x-4 gap-y-1">
				{#each characteristics as ch (ch.key)}
					<span class="flex items-center gap-1.5 text-sm text-ink-muted">{ch.label} {@render statusBadge(ch.state)}</span>
				{/each}
			</div>
			<div class="flex flex-wrap items-center gap-2 sm:ml-auto">
				<span class="hidden text-sm text-ink-muted xl:inline">Enter accepts, the right arrow or Space skips, the left arrow goes back</span>
				<Popover label="Why reject this sample" width="17rem" placement="bottom-end" bind:open={rejectOpen}>
					{#snippet trigger(props)}
						<Button {...props} size="sm" icon={Ban}>{rejected ? 'Rejected' : 'Reject'}</Button>
					{/snippet}
					<div class="label mb-2">Reject this sample, because</div>
					<div class="flex flex-col gap-2">
						{#each REJECT_REASONS as r (r.value)}
							<Checkbox checked={rejectReasons.has(r.value)} onchange={() => toggleReason(r.value)}>{r.label}</Checkbox>
						{/each}
					</div>
					<div class="mt-3 flex justify-end">
						<Button variant="danger" size="sm" loading={rejecting} disabled={rejectReasons.size === 0} onclick={submitReject}
							>Reject and go on</Button
						>
					</div>
				</Popover>
				<!-- Skip is always there, and resets what was recorded for this piece
				     (skipAndReset); the accept appears once something is entered. -->
				<Button variant="ghost" size="sm" onclick={skipAndReset}>Skip</Button>
				{#if touched.length > 0}
					<Button variant="primary" size="sm" icon={ArrowRight} loading={cropSaving} onclick={commitAndAdvance}>{ctaLabel}</Button>
				{/if}
			</div>
		</div>
	</Panel>
{/snippet}

<!-- The piece itself: its crops, and the model's and the pixels' color -->
{#snippet pieceCard()}
	{#if detail}
		<Panel
			title={detail.part.part_name || detail.part.part_id || 'Unidentified'}
			description={`${detail.part.part_id ? `${detail.part.part_id}, ` : ''}${detail.machine_name ?? 'Machine'}`}
		>
			<div class="flex flex-wrap gap-2">
				{#each detail.images as img (img.seq)}
					<div class="relative">
						<ZoomImage
							src={api.colorLabelImageUrl(machineId, pieceUuid, img.seq)}
							alt={`Crop ${img.seq}`}
							title={`Crop ${img.seq}${img.source ? `, ${img.source}` : ''}`}
							class="size-28 rounded-item object-contain"
						/>
						{#if img.used}
							<span class="absolute right-0.5 bottom-0.5 inline-flex h-(--size-badge) items-center rounded-badge bg-success px-1.5 text-xs font-medium text-on-success"
								>Used</span
							>
						{/if}
						{@render qualityOverlay(img, 'piece_image', img.seq)}
					</div>
				{/each}
			</div>

			<div class="mt-4 flex flex-col gap-3 border-t border-line pt-4">
				{#if detail.model_prediction}
					{@const mp = detail.model_prediction}
					<div class="flex items-center gap-3">
						<span class="size-10 shrink-0 rounded-item border border-line" style={`background:#${mp.rgb ?? '888888'}`} title={`The model's color, #${mp.rgb ?? '?'}`}></span>
						<div class="min-w-0 text-sm text-ink-muted">
							<div class="flex items-center gap-1.5 font-medium text-ink">
								<Sparkles size={14} class="text-info-ink" /> The model's color <span class="font-normal text-ink-muted">{mp.model_name}</span>
							</div>
							<div class="num">
								<span class="text-ink">{mp.color_name ?? mp.color_id}</span> ({mp.color_id}), {Math.round(mp.confidence * 100)}% from {mp.sample_count}
								crop{mp.sample_count === 1 ? '' : 's'}
							</div>
						</div>
					</div>
				{/if}

				{#if detail.pixel_guess}
					{@const pg = detail.pixel_guess}
					<div class="flex items-center gap-3 {detail.model_prediction ? 'opacity-70' : ''}">
						<span class="size-10 shrink-0 rounded-item border border-line" style={`background:#${pg.rgb}`} title={`The pixels' average, #${pg.rgb}`}></span>
						<div class="min-w-0 text-sm text-ink-muted">
							<div class="font-medium text-ink">The pixels' average</div>
							<div class="num flex items-center gap-1.5">
								{#if pg.color_id != null && colorsById.has(pg.color_id)}
									<span class="inline-block size-3.5 rounded-check border border-line" style={`background:#${colorsById.get(pg.color_id)?.rgb ?? '000'}`}></span>
								{/if}
								<span><span class="text-ink">{pg.color_name}</span> ({pg.color_id}), the nearest over {pg.sample_count} crop{pg.sample_count === 1 ? '' : 's'}</span>
							</div>
						</div>
					</div>
				{/if}

				{#if !detail.model_prediction && !detail.pixel_guess}
					<p class="text-sm text-ink-muted">No suggestion: the crops are not available.</p>
				{/if}
			</div>
		</Panel>
	{/if}
{/snippet}

<!-- The same physical piece in the channels before it -->
{#snippet cropsCard()}
	<Panel
		title="Same piece across channels"
		description="Our guess at which C2 and C3 crops are this same physical piece. Keep or drop the picks, add any we missed, then accept."
	>
		{#snippet actions()}{@render statusBadge(piecesState)}{/snippet}
		<div class="mb-3 flex flex-wrap items-center gap-2">
			<span class="num mr-auto text-sm text-ink-muted">{cropSelected.size} of {cropCandidates.length} chosen</span>
			<Button size="sm" variant="ghost" disabled={cropSelected.size === 0 || cropLoading} onclick={selectNoCrops}>Choose none</Button>
			<Button size="sm" loading={cropSaving} disabled={cropCandidates.length === 0 || cropLoading} onclick={rejectAllCrops}>None of these</Button>
			{#if canRunAi}
				<Button size="sm" icon={Sparkles} loading={aiRunning} disabled={cropCandidates.length === 0 || cropLoading} onclick={runAiPredict}>Run AI</Button>
			{/if}
			<Button
				size="sm"
				variant={cropDirty ? 'primary' : 'secondary'}
				loading={cropSaving}
				disabled={cropCandidates.length === 0 || cropLoading}
				onclick={saveCrops}>Accept</Button
			>
		</div>
		<p class="mb-3 flex items-center gap-1.5 text-sm text-ink-muted">
			{#if predictionSource === 'ai'}
				<Sparkles size={14} class="shrink-0 text-info-ink" />Picks from a vision model{aiReasoning ? `: ${aiReasoning}` : '.'}
			{:else if predictionSource === 'model'}
				<Sparkles size={14} class="shrink-0 text-info-ink" />Picks from the link model{linkModel ? ` (${linkModel})` : ''}.{canRunAi
					? ' Run AI for a vision model\'s guess.'
					: ''}
			{:else}
				Picks from the time and angle guess.{canRunAi ? ' Run AI for a vision model\'s guess.' : ''}
			{/if}
		</p>

		{#if cropLoading}
			<div class="flex justify-center py-8"><Spinner size={32} /></div>
		{:else if cropError}
			<Alert tone="danger">{cropError}</Alert>
		{:else if cropCandidates.length === 0}
			<p class="py-4 text-sm text-ink-muted">No candidate crops in range for this piece.</p>
		{:else}
			<div class="flex max-h-[42vh] flex-wrap gap-2 overflow-y-auto pr-1">
				{#each cropCandidates as c (c.local_id)}
					{@const selected = cropSelected.has(c.local_id)}
					{@const isPick = isPredictionPick(c, predictionSource)}
					<div class="relative">
						<button
							type="button"
							onclick={() => toggleCrop(c.local_id)}
							aria-pressed={selected}
							title={`C${c.channel}, ${ZONE_LABEL[c.zone_code ?? 0] ?? '?'}, ${c.dt != null ? c.dt + ' s before arrival' : 'arrival unknown'}${c.com_forward_to_exit_deg != null ? `, ${Math.round(c.com_forward_to_exit_deg)}° to the exit` : ''}, score ${c.score}${predictionSource === 'model' && c.model_score != null ? `, model ${c.model_score}` : ''}${isPick ? `, the ${SOURCE_PICK_LABEL[predictionSource]} pick` : ''}`}
							class="flex flex-col items-center gap-1 rounded-item p-1 {selected ? 'bg-primary-soft' : 'bg-well opacity-70 hover:opacity-100'}"
						>
							{#if c.available}
								<img src={api.channelCropLabelImageUrl(machineId, c.local_id)} alt={`Crop ${c.local_id}`} loading="lazy" class="size-16 rounded-item object-contain" />
							{:else}
								<div class="flex size-16 items-center justify-center text-sm text-ink-faint">Gone</div>
							{/if}
							<span class="num flex items-center gap-1 text-sm {selected ? 'font-medium text-primary-ink' : 'text-ink-muted'}">
								{#if selected}<Check size={14} />{/if}C{c.channel}, {c.dt} s
							</span>
						</button>
						{#if isPick}
							<span class="pointer-events-none absolute top-0.5 right-0.5 flex rounded-badge bg-info p-0.5 text-on-info" title={`The ${SOURCE_PICK_LABEL[predictionSource]} guess`}
								><Sparkles size={14} /></span
							>
						{/if}
						{@render qualityOverlay(c, 'channel_crop', c.local_id)}
					</div>
				{/each}
			</div>
		{/if}
	</Panel>
{/snippet}

<!-- The true part -->
{#snippet partPicker()}
	{#if detail}
		<Panel title="True part" class="shrink-0">
			{#snippet actions()}{@render statusBadge(partState)}{/snippet}
			<div class="max-h-[55vh] overflow-y-auto">
				<PiecePartPicker
					predictedPart={detail.predicted_part}
					selectedPart={myPart}
					cantTell={partCantTell}
					saving={partSaving}
					onPick={(partNum) => void pickPart(partNum)}
					onCantTell={() => void pickPartCantTell()}
					onClear={() => void clearPartAnswer()}
				/>
			</div>
		</Panel>
	{/if}
{/snippet}

{#snippet colorRow(color: BrickLinkColor, isGuess: boolean)}
	{@const selected = color.id === myColorId}
	<button
		type="button"
		aria-pressed={selected}
		class="flex items-center gap-2 rounded-item px-2 py-1 text-left disabled:opacity-45 {selected
			? 'bg-primary-soft'
			: isGuess
				? 'bg-info-soft hover:bg-hover'
				: 'hover:bg-hover'}"
		title={`${color.name} (${color.id})`}
		onclick={() => pickColor(color.id)}
		disabled={submitting}
	>
		<span class="size-5 shrink-0 rounded-check border border-line {color.is_trans ? 'opacity-70' : ''}" style={`background:#${color.rgb ?? '000'}`}></span>
		<span class="min-w-0 flex-1 truncate text-sm {selected ? 'font-medium text-primary-ink' : 'text-ink'}"
			>{color.name}{#if isGuess}<span class="ml-1 text-info-ink">(the guess)</span>{/if}</span
		>
		{#if selected}<Check size={16} class="shrink-0 text-primary-ink" />{/if}
	</button>
{/snippet}

<!-- The true color. In the pane the list has a fixed height; on the page it
     fills the sticky column and scrolls. -->
{#snippet colorPicker()}
	<Panel title="True color" fill={layout === 'page'} class={layout === 'page' ? 'min-h-0 flex-1' : ''}>
		{#snippet actions()}{@render statusBadge(colorState)}{/snippet}
		<div class="flex min-h-0 flex-col gap-3 {layout === 'page' ? 'h-full' : ''}">
			<button
				type="button"
				aria-pressed={cantTell}
				class="flex items-center gap-2 rounded-item px-2 py-1.5 text-left text-sm disabled:opacity-45 {cantTell
					? 'bg-primary-soft font-medium text-primary-ink'
					: 'bg-well text-ink-muted hover:bg-hover'}"
				onclick={pickCantTell}
				disabled={submitting}
			>
				<Ban size={16} class="shrink-0" />
				<span class="flex-1">I can't tell the color</span>
				{#if cantTell}<Check size={16} class="shrink-0" />{/if}
			</button>

			{#if guessColorId != null && colorsById.get(guessColorId)}
				{@render colorRow(colorsById.get(guessColorId)!, true)}
			{/if}

			{#if !search.trim() && similarColors.length > 0}
				<div>
					<div class="label mb-1.5">Closest to the guess</div>
					<div class="flex flex-col gap-0.5">
						{#each similarColors as color (color.id)}{@render colorRow(color, false)}{/each}
					</div>
				</div>
				<div class="label">Every color</div>
			{/if}

			<Input type="search" bind:value={search} placeholder="Search the colors" />

			<div class="flex min-h-0 flex-col gap-0.5 overflow-y-auto pr-1 {layout === 'page' ? 'flex-1' : 'max-h-[60vh]'}">
				{#each filteredColors as color (color.id)}{@render colorRow(color, false)}{/each}
			</div>
			{#if filteredColors.length === 0}
				<p class="py-4 text-center text-sm text-ink-muted">No colors match "{search}".</p>
			{/if}
		</div>
	</Panel>
{/snippet}

<!-- Brickognize's part, to confirm or correct, only when the piece has a
     Brickognize listing. A color that disagrees with Brickognize's goes to it on
     its own when the labeler moves on (its color is never shown). -->
{#snippet brickognizeCard()}
	{#if detail && correction?.correctable}
		{@const partSent = correction.part_feedback_submitted}
		<Panel title="Is this the right part?" class="shrink-0">
			{#snippet actions()}{#if partSent}<Badge tone="success" dot>Sent</Badge>{/if}{/snippet}
			<div class="flex flex-col gap-3">
				<div class="flex items-center gap-2 text-sm text-ink">
					<span class="truncate">{detail.part.part_name || detail.part.part_id || 'Unidentified'}</span>
					{#if detail.part.part_id}<span class="font-mono text-ink-muted">{detail.part.part_id}</span>{/if}
				</div>
				{#if partSent}
					<p class="text-sm text-ink-muted">Your answer went to Brickognize.</p>
				{:else}
					<SegmentedControl
						label="Is it the right part"
						size="sm"
						value={partVerdict === true ? 'right' : partVerdict === false ? 'wrong' : ''}
						options={[
							{ value: 'right', label: 'Right', icon: Check },
							{ value: 'wrong', label: 'Wrong', icon: Ban }
						]}
						onchange={(v: string) => (partVerdict = v === 'right')}
					/>
				{/if}
				{#if feedback}<Alert tone={feedback.variant}>{feedback.text}</Alert>{/if}
			</div>
			{#snippet footer()}
				<Button variant="primary" size="sm" loading={sendingFeedback} disabled={partSent || partVerdict == null} onclick={sendBrickognizeFeedback}
					>{partSent ? 'Sent to Brickognize' : 'Send to Brickognize'}</Button
				>
			{/snippet}
		</Panel>
	{/if}
{/snippet}

<!-- For reference: this machine's labeled colors (what is true here) and the
     part's colors on BrickLink (what exists at all) -->
{#snippet referenceCols()}
	{#if detail}
		<div class="flex flex-col gap-(--gap-panels) {layout === 'page' ? 'sm:flex-row' : ''}">
			<div class="min-w-0 flex-1 {layout === 'page' ? 'lg:overflow-y-auto' : ''}">
				<MachineLabeledPieces {machineId} {pieceUuid} />
			</div>
			<div class="min-w-0 flex-1 {layout === 'page' ? 'lg:overflow-y-auto' : ''}">
				<PartBrickLinkColors
					palette={colors}
					items={blItems}
					{guessColorId}
					partName={myPart?.name ?? detail.part.part_name}
					itemNo={blItemNo}
					updatedAt={blUpdatedAt}
					source={blSource}
					loading={blLoading}
					error={blError}
				/>
			</div>
		</div>
	{/if}
{/snippet}

{#snippet directions()}
	<Panel title="How to label a piece">
		<ol class="flex list-decimal flex-col gap-2 pl-5 text-sm text-ink">
			<li>Judge the piece's true color from the crops of <span class="font-medium">both channels</span>.</li>
			<li>Pick the color in the column. If you can tell it, that is enough: you can skip the same-piece step.</li>
			<li>
				Under <span class="font-medium">True part</span>, confirm the mold the machine guessed or search the catalog for the right
				one. If the piece came back unidentified, search for what it is.
			</li>
			<li>
				Under <span class="font-medium">Same piece across channels</span>, keep or add the earlier crops of this same piece. Skip
				it if the piece's own box already shows all of it.
			</li>
			<li>
				Try to do both for each piece. If you can't tell the color, or can't find the piece in the earlier pictures, do the half
				you are sure of and go on.
			</li>
		</ol>
	</Panel>
{/snippet}

<div class="flex flex-col gap-(--gap-panels)">
	{@render header()}

	{#if error}<Alert tone="danger">{error}</Alert>{/if}

	{#if loading}
		<div class="flex justify-center py-16"><Spinner size={32} /></div>
	{:else if !detail}
		<Panel><EmptyState title="Piece not found" /></Panel>
	{:else}
		{@render summaryBar()}

		{#if layout === 'page'}
			<!-- The wide page: reference, then the piece, then the color and part column -->
			<div class="flex flex-col gap-(--gap-panels) lg:flex-row lg:items-start">
				<aside
					class="flex shrink-0 flex-col gap-(--gap-panels) sm:flex-row lg:sticky lg:top-[calc(var(--size-topbar)+1rem)] lg:h-[calc(100dvh-var(--size-topbar)-2rem)] lg:w-[26rem]"
				>
					{@render referenceCols()}
				</aside>
				<div class="flex min-w-0 flex-col gap-(--gap-panels) lg:flex-1">
					{@render pieceCard()}
					{@render cropsCard()}
				</div>
				<div
					class="flex flex-col gap-(--gap-panels) lg:sticky lg:top-[calc(var(--size-topbar)+1rem)] lg:max-h-[calc(100dvh-var(--size-topbar)-2rem)] lg:w-96"
				>
					{@render partPicker()}
					{@render colorPicker()}
					{@render brickognizeCard()}
				</div>
			</div>
			{@render directions()}
		{:else}
			<!-- The pane beside the list: one column -->
			{@render pieceCard()}
			{@render colorPicker()}
			{@render partPicker()}
			{@render cropsCard()}
			{@render brickognizeCard()}
			{@render referenceCols()}
		{/if}
	{/if}
</div>
