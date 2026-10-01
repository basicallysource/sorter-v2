<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';
	import Search from '@lucide/svelte/icons/search';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import { untrack } from 'svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Popover from '$lib/components/ui/Popover.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import {
		fetchLegoColors,
		swatchHex,
		type BrickLinkColor,
		type PieceSummary
	} from '$lib/pieces';

	// Reusable Brickognize correction controls. Render only when
	// `piece.correctable === true` — the parent is responsible for that gate, but
	// the component also no-ops defensively if handed a non-correctable piece.
	//
	// Two independent verdicts:
	//   • PART — a check/X marking whether the predicted PART TYPE was right. This
	//     is ONLY about the part, never the color.
	//   • COLOR — a searchable dropdown of the whole BrickLink palette. The
	//     predicted color is pre-selected and flagged; the user can pick another
	//     and Confirm to lock it in.
	//
	// Every mutation POSTs to /api/pieces/{uuid}/correction (submit:true) and the
	// parent is handed the fresh summary via `onUpdated` so it can update in place.
	let {
		piece,
		endpointBase,
		onUpdated,
		compact = false
	}: {
		piece: PieceSummary;
		endpointBase: string;
		onUpdated?: (summary: PieceSummary) => void;
		// Slightly tighter layout for the modal/popover surface.
		compact?: boolean;
	} = $props();

	type CorrectionResponse = {
		summary: PieceSummary;
		part_submitted: boolean;
		color_submitted: boolean;
		submit_error: string | null;
	};

	// Operator-flagged attributes of the sample. Most codes match Hive's
	// piece_rejections vocabulary (no_piece / multiple_pieces / not_lego /
	// assembly / pieces_entangled) so the two systems agree on what those strings
	// mean once synced. "assembly" (parts built into one unit) and
	// "pieces_entangled" (separate parts stuck together) are distinct concepts,
	// kept as samples but still reject reasons. "blurry" is Sorter-only — the
	// machine-side rejection_reasons column has no fixed enum, so it just rides
	// along; nothing in Hive validates against it. Multiple can apply at once.
	const REJECTION_REASONS: { code: string; label: string }[] = [
		{ code: 'not_lego', label: 'Not LEGO' },
		{ code: 'multiple_pieces', label: 'Multiple pieces in frame' },
		{ code: 'no_piece', label: 'No piece in frame' },
		{ code: 'assembly', label: 'Assembly' },
		{ code: 'pieces_entangled', label: 'Pieces entangled' },
		{ code: 'blurry', label: 'Blurry' }
	];

	let colors = $state<BrickLinkColor[]>([]);
	let colorsLoading = $state(false);
	let colorsError = $state<string | null>(null);

	let partBusy = $state(false);
	let colorBusy = $state(false);
	// Result banner after a correction call: success (reached Brickognize),
	// warning (recorded locally but Brickognize didn't accept it), or danger
	// (the request itself failed, nothing saved).
	let feedback = $state<{ variant: 'success' | 'warning' | 'danger'; text: string } | null>(null);

	// Color dropdown state.
	let pickerOpen = $state(false);
	let query = $state('');
	// The staged selection (BrickLink id as string) before Confirm. Initialized
	// to the already-corrected color if present, else the prediction.
	let selectedId = $state<string | null>(null);

	const predictedColorId = $derived(piece.color_id ?? null);
	const committedColorId = $derived(piece.color_corrected_id ?? null);

	async function loadColors() {
		if (colors.length > 0 || colorsLoading) return;
		colorsLoading = true;
		colorsError = null;
		try {
			colors = await fetchLegoColors(endpointBase);
		} catch {
			colorsError = 'Could not load the color list.';
		} finally {
			colorsLoading = false;
		}
	}

	// The popover opens from its own button; each time it does, the staged
	// choice starts from the committed correction, else the prediction.
	$effect(() => {
		if (!pickerOpen) return;
		untrack(() => {
			selectedId = committedColorId ?? predictedColorId ?? null;
			query = '';
			void loadColors();
		});
	});

	const filteredColors = $derived.by(() => {
		const q = query.trim().toLowerCase();
		if (!q) return colors;
		return colors.filter((c) => c.name.toLowerCase().includes(q));
	});

	function colorNameFor(id: string | null): string | null {
		if (!id) return null;
		const match = colors.find((c) => String(c.id) === id);
		return match?.name ?? null;
	}

	function colorRgbFor(id: string | null): string | null {
		if (!id) return null;
		return colors.find((c) => String(c.id) === id)?.rgb ?? null;
	}

	async function postCorrection(body: {
		part_correct?: boolean | null;
		color_corrected_id?: string | null;
		rejection_reasons?: string[] | null;
		submit?: boolean;
	}): Promise<CorrectionResponse | null> {
		const res = await fetch(
			`${endpointBase}/api/pieces/${encodeURIComponent(piece.uuid)}/correction`,
			{
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body)
			}
		);
		if (!res.ok) throw new Error(`correction ${res.status}`);
		return (await res.json()) as CorrectionResponse;
	}

	// Turn a correction response into a result banner. `sent` is the channel's
	// submitted flag (part_submitted / color_submitted) for the "reached
	// Brickognize" success message.
	function applyResponse(resp: CorrectionResponse, noun: string, sent: boolean) {
		onUpdated?.(resp.summary);
		if (resp.submit_error) {
			feedback = {
				variant: 'warning',
				text: `${noun} saved, but Brickognize didn't accept it: ${resp.submit_error}`
			};
		} else if (sent) {
			feedback = { variant: 'success', text: `${noun} sent to Brickognize.` };
		} else {
			feedback = { variant: 'success', text: `${noun} saved.` };
		}
	}

	async function setPartVerdict(verdict: boolean) {
		if (partBusy) return;
		partBusy = true;
		feedback = null;
		try {
			const resp = await postCorrection({ part_correct: verdict, submit: true });
			if (resp) applyResponse(resp, 'Part verdict', resp.part_submitted);
		} catch {
			feedback = { variant: 'danger', text: 'Failed to reach the machine — nothing was saved.' };
		} finally {
			partBusy = false;
		}
	}

	let rejectionBusy = $state(false);
	const rejectionReasons = $derived(new Set(piece.rejection_reasons ?? []));

	async function toggleRejectionReason(code: string) {
		if (rejectionBusy) return;
		rejectionBusy = true;
		feedback = null;
		const next = new Set(rejectionReasons);
		if (next.has(code)) next.delete(code);
		else next.add(code);
		try {
			const resp = await postCorrection({
				rejection_reasons: Array.from(next),
				submit: true
			});
			if (resp) {
				onUpdated?.(resp.summary);
				feedback = { variant: 'success', text: 'Issue flags saved.' };
			}
		} catch {
			feedback = { variant: 'danger', text: 'Failed to reach the machine — nothing was saved.' };
		} finally {
			rejectionBusy = false;
		}
	}

	async function submitColor(id: string | null) {
		if (colorBusy || !id) return;
		colorBusy = true;
		feedback = null;
		try {
			const resp = await postCorrection({ color_corrected_id: id, submit: true });
			if (resp) {
				applyResponse(resp, 'Color correction', resp.color_submitted);
				pickerOpen = false;
			}
		} catch {
			feedback = { variant: 'danger', text: 'Failed to reach the machine — nothing was saved.' };
		} finally {
			colorBusy = false;
		}
	}

	// One click: the predicted color is right (submits the prediction, which
	// Brickognize records as an accept).
	function acceptPredictedColor() {
		void submitColor(predictedColorId);
	}

	// The dropdown's Confirm: submit whatever the user staged (possibly different).
	function confirmColor() {
		void submitColor(selectedId);
	}

	function chooseColor(id: string) {
		selectedId = id;
	}

	// Load colors eagerly so the committed/predicted swatch renders with a name
	// even before the picker is opened.
	$effect(() => {
		if (piece.correctable) void loadColors();
	});

	const partVerdict = $derived(piece.part_correct ?? null);
	const partSent = $derived(Boolean(piece.part_feedback_submitted));
	const colorSent = $derived(Boolean(piece.color_feedback_submitted));

	// The Brickognize-predicted color (what "Yes" accepts).
	const predictedColorName = $derived(colorNameFor(predictedColorId) ?? piece.color_name ?? null);
	const predictedColorHex = $derived(swatchHex(colorRgbFor(predictedColorId)));
	// The committed correction, if the user chose a different color.
	const committedColorName = $derived(colorNameFor(committedColorId));
	const committedColorHex = $derived(swatchHex(colorRgbFor(committedColorId)));
	const acceptedPrediction = $derived(
		committedColorId != null && committedColorId === predictedColorId
	);
	const correctedToDifferent = $derived(
		committedColorId != null && committedColorId !== predictedColorId
	);

	const gap = $derived(compact ? 'gap-2' : 'gap-3');
</script>

{#if piece.correctable}
	<div class="flex flex-col {gap}">
		<!-- The part verdict: only about the part type, never the color -->
		<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
			<span class="label">Part correct?</span>
			<SegmentedControl
				label="Is the predicted part type right?"
				size="sm"
				value={partVerdict === true ? 'yes' : partVerdict === false ? 'no' : ''}
				options={[
					{ value: 'yes', label: 'Yes', icon: Check },
					{ value: 'no', label: 'No', icon: X }
				]}
				onchange={(verdict) => void setPartVerdict(verdict === 'yes')}
			/>
			{#if partBusy}
				<Spinner size={14} />
			{:else if partSent}
				<span title="This part verdict has been sent to Brickognize"><Badge tone="success">Sent</Badge></span>
			{/if}
			<span class="text-sm text-ink-muted">Part type only, not the color.</span>
		</div>

		<!-- The color verdict -->
		<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
			<span class="label">Color correct?</span>
			<!-- The predicted color, with a one-click "yes, it is right". A color is data, so its swatch is that color. -->
			<span class="inline-flex items-center gap-2 text-sm text-ink" title="Brickognize predicted this color">
				{#if predictedColorHex}
					<span class="size-4 rounded-check border border-line" style:background-color={predictedColorHex}></span>
				{/if}
				{predictedColorName ?? '—'}
			</span>
			<Button
				size="sm"
				variant={acceptedPrediction ? 'primary' : 'secondary'}
				icon={Check}
				disabled={colorBusy || predictedColorId == null}
				onclick={acceptPredictedColor}
			>
				Yes
			</Button>
			<!-- Or pick a different, correct color. -->
			<Popover label="Pick the correct color" bind:open={pickerOpen} width="22rem" padded={false}>
				{#snippet trigger(props)}
					<Button {...props} size="sm" variant={correctedToDifferent ? 'primary' : 'secondary'}>
						{#if correctedToDifferent && committedColorHex}
							<span class="size-4 rounded-check border border-line" style:background-color={committedColorHex}></span>
						{:else}
							<Search size={14} />
						{/if}
						{correctedToDifferent ? committedColorName : 'No, pick the color'}
					</Button>
				{/snippet}
				<div class="p-2">
					<Input aria-label="Search colors" placeholder="Search colors…" bind:value={query} />
				</div>
				<div class="max-h-56 overflow-y-auto border-t border-line py-1">
					{#if colorsLoading && colors.length === 0}
						<p class="flex items-center gap-2 px-3 py-2 text-sm text-ink-muted">
							<Spinner size={14} />
							Loading the colors
						</p>
					{:else if colorsError}
						<div class="p-2"><Alert tone="danger">{colorsError}</Alert></div>
					{:else}
						{#each filteredColors as c (c.id)}
							{@const idStr = String(c.id)}
							{@const hex = swatchHex(c.rgb)}
							{@const isSelected = idStr === selectedId}
							<button
								type="button"
								onclick={() => chooseColor(idStr)}
								class="flex min-h-(--size-menu-item) w-full items-center gap-2 px-3 text-left text-sm text-ink hover:bg-hover {isSelected
									? 'bg-primary-soft'
									: ''}"
							>
								<span
									class="size-4 shrink-0 rounded-check border border-line"
									style:background-color={hex ?? 'transparent'}
								></span>
								<span class="min-w-0 flex-1 truncate">{c.name}</span>
								{#if c.is_trans}<span class="text-xs text-ink-muted">trans</span>{/if}
								{#if idStr === predictedColorId}
									<span title="Brickognize predicted this color">
										<Badge tone="info">
											<Sparkles size={12} />
											Prediction
										</Badge>
									</span>
								{/if}
								{#if isSelected}<Check size={16} class="shrink-0 text-primary-ink" />{/if}
							</button>
						{:else}
							<p class="px-3 py-2 text-sm text-ink-muted">No colors match.</p>
						{/each}
					{/if}
				</div>
				<div class="flex items-center justify-end gap-2 border-t border-line p-2">
					<Button variant="ghost" size="sm" onclick={() => (pickerOpen = false)}>Cancel</Button>
					<Button variant="primary" size="sm" loading={colorBusy} disabled={!selectedId} onclick={confirmColor}>
						Confirm color
					</Button>
				</div>
			</Popover>
			{#if colorBusy}
				<Spinner size={14} />
			{:else if colorSent}
				<span title="This color correction has been sent to Brickognize"><Badge tone="success">Sent</Badge></span>
			{/if}
		</div>

		<!-- Capture-issue flags: any number can apply -->
		<div class="flex flex-wrap items-center gap-2">
			<span class="label mr-1">Report an issue</span>
			{#each REJECTION_REASONS as reason (reason.code)}
				{@const active = rejectionReasons.has(reason.code)}
				<Button
					size="sm"
					variant={active ? 'primary' : 'secondary'}
					aria-pressed={active}
					disabled={rejectionBusy}
					onclick={() => toggleRejectionReason(reason.code)}
				>
					{reason.label}
				</Button>
			{/each}
			{#if rejectionBusy}<Spinner size={14} />{/if}
		</div>

		<!-- Reserve the banner's height whether or not it is showing: a message
		     appearing after a click must not reflow what surrounds it. -->
		<div class="mt-1 min-h-[2.75rem]">
			{#if feedback}<Alert tone={feedback.variant}>{feedback.text}</Alert>{/if}
		</div>
	</div>
{/if}
