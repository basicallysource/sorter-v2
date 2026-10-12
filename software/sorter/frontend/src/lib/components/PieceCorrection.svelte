<script lang="ts">
	import PieceReview from '$lib/components/ui/PieceReview.svelte';
	import type { LikelyColor } from '$lib/components/ui/ColorChoice.svelte';
	import { fetchLegoColors, type BrickLinkColor, type PieceSummary } from '$lib/pieces';

	// The review of one correctable piece (the dashboard's correction dialog and
	// the records list): the design system's PieceReview, fed from this
	// machine's API. Render only when `piece.correctable` (a Brickognize listing
	// was captured); the parent gates that.
	//
	// Every answer POSTs /api/pieces/{uuid}/correction (submit:true, so a new
	// verdict goes to Brickognize) and hands the fresh summary to `onUpdated`.
	// The likely colors come from /api/pieces/{uuid}/likely-colors when the
	// colors open, or at once with `prefetch` (the dialog, opened to review).
	let {
		piece,
		endpointBase,
		onUpdated,
		prefetch = false
	}: {
		piece: PieceSummary;
		endpointBase: string;
		onUpdated?: (summary: PieceSummary) => void;
		prefetch?: boolean;
	} = $props();

	type CorrectionResponse = {
		summary: PieceSummary;
		part_submitted: boolean;
		color_submitted: boolean;
		submit_error: string | null;
	};

	type LikelyResponse = {
		source: 'live' | 'cache' | 'none';
		colors: LikelyColor[];
		fallback: 'hive_unreachable' | 'hive_too_old' | 'no_hive' | 'no_part' | null;
	};

	// Operator-flagged attributes of the sample. Most codes match Hive's
	// piece_rejections vocabulary (no_piece / multiple_pieces / not_lego /
	// assembly / pieces_entangled) so the two systems agree on what they mean
	// once synced. "blurry" is Sorter-only and rides along unvalidated.
	const ISSUES = [
		{ code: 'not_lego', label: 'Not LEGO' },
		{ code: 'multiple_pieces', label: 'Multiple pieces in frame' },
		{ code: 'no_piece', label: 'No piece in frame' },
		{ code: 'assembly', label: 'Assembly' },
		{ code: 'pieces_entangled', label: 'Pieces entangled' },
		{ code: 'blurry', label: 'Blurry' }
	];

	let palette = $state<BrickLinkColor[]>([]);
	let likely = $state<LikelyColor[] | null>(null);
	let likelyNote = $state<string | null>(null);
	let likelyFor = '';

	let partBusy = $state(false);
	let colorBusy = $state(false);
	let issuesBusy = $state(false);
	let notice = $state<{ tone: 'warning' | 'danger'; text: string } | null>(null);

	const isColorId = (id: string | null | undefined): id is string =>
		typeof id === 'string' && /^\d+$/.test(id) && Number(id) > 0;

	// The color the piece was given, when it is a real one (not "any_color").
	const predicted = $derived.by(() => {
		if (!isColorId(piece.color_id)) return null;
		const id = Number(piece.color_id);
		const known = palette.find((c) => c.id === id);
		return known ?? { id, name: piece.color_name ?? `Color ${id}`, rgb: null };
	});
	const predictedMark = $derived(
		typeof piece.color_confidence === 'number'
			? `Predicted ${Math.round(piece.color_confidence * 100)}%`
			: 'Predicted'
	);
	const correctedId = $derived(
		isColorId(piece.color_corrected_id) ? Number(piece.color_corrected_id) : null
	);

	$effect(() => {
		void fetchLegoColors(endpointBase)
			.then((colors) => {
				palette = colors;
				if (colors.length === 0) {
					notice = {
						tone: 'warning',
						text: 'The color list is not here yet: this machine has not reached Hive.'
					};
				}
			})
			.catch(() => {
				notice = { tone: 'danger', text: 'Could not load the color list from the machine.' };
			});
	});

	async function loadLikely() {
		const key = `${endpointBase}|${piece.uuid}|${piece.color_id}`;
		if (likelyFor === key) return;
		likelyFor = key;
		likely = null;
		likelyNote = null;
		try {
			const res = await fetch(
				`${endpointBase}/api/pieces/${encodeURIComponent(piece.uuid)}/likely-colors`
			);
			if (!res.ok) throw new Error(`likely colors ${res.status}`);
			const body = (await res.json()) as LikelyResponse;
			if (likelyFor !== key) return;
			likely = body.colors;
			likelyNote =
				body.fallback === 'hive_unreachable' || body.fallback === 'no_hive'
					? 'By color alone: the machine cannot reach Hive.'
					: body.fallback === 'hive_too_old'
						? 'By color alone: this Hive does not rank colors yet.'
						: body.source === 'none'
							? 'By color alone: no BrickLink numbers for this part.'
							: null;
		} catch {
			if (likelyFor !== key) return;
			likely = [];
			likelyNote = 'Could not rank the colors; pick from every color below.';
			likelyFor = '';
		}
	}

	$effect(() => {
		if (prefetch && piece.correctable) void loadLikely();
	});

	async function postCorrection(body: {
		part_correct?: boolean | null;
		color_corrected_id?: string | null;
		rejection_reasons?: string[] | null;
	}): Promise<CorrectionResponse> {
		const res = await fetch(
			`${endpointBase}/api/pieces/${encodeURIComponent(piece.uuid)}/correction`,
			{
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ ...body, submit: true })
			}
		);
		if (!res.ok) throw new Error(`correction ${res.status}`);
		return (await res.json()) as CorrectionResponse;
	}

	// A saved answer shows as its filled button (and "Sent"); only what went
	// wrong needs words.
	function applyResponse(resp: CorrectionResponse) {
		onUpdated?.(resp.summary);
		notice = resp.submit_error
			? { tone: 'warning', text: `Saved, but Brickognize did not accept it: ${resp.submit_error}` }
			: null;
	}

	const failed = {
		tone: 'danger',
		text: 'Could not reach the machine; nothing was saved.'
	} as const;

	async function setPart(correct: boolean) {
		if (partBusy) return;
		partBusy = true;
		try {
			applyResponse(await postCorrection({ part_correct: correct }));
		} catch {
			notice = failed;
		} finally {
			partBusy = false;
		}
	}

	async function setColor(id: number): Promise<boolean> {
		if (colorBusy) return false;
		colorBusy = true;
		try {
			applyResponse(await postCorrection({ color_corrected_id: String(id) }));
			return true;
		} catch {
			notice = failed;
			return false;
		} finally {
			colorBusy = false;
		}
	}

	async function toggleIssue(code: string) {
		if (issuesBusy) return;
		issuesBusy = true;
		const next = new Set(piece.rejection_reasons ?? []);
		if (next.has(code)) next.delete(code);
		else next.add(code);
		try {
			applyResponse(await postCorrection({ rejection_reasons: Array.from(next) }));
		} catch {
			notice = failed;
		} finally {
			issuesBusy = false;
		}
	}
</script>

{#if piece.correctable}
	<PieceReview
		{palette}
		{likely}
		{likelyNote}
		{predicted}
		{predictedMark}
		{correctedId}
		partVerdict={piece.part_correct ?? null}
		partSent={Boolean(piece.part_feedback_submitted)}
		{partBusy}
		colorSent={Boolean(piece.color_feedback_submitted)}
		{colorBusy}
		issues={ISSUES}
		activeIssues={piece.rejection_reasons ?? []}
		{issuesBusy}
		{notice}
		onpart={(correct) => void setPart(correct)}
		oncolor={setColor}
		onissue={(code) => void toggleIssue(code)}
		onpicking={(open) => {
			if (open) void loadLikely();
		}}
	/>
{/if}
