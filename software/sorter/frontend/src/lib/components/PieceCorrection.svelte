<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';
	import Search from '@lucide/svelte/icons/search';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import Button from '$lib/components/ui/Button.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import {
		fetchLegoColors,
		swatchHex,
		swatchTextColor,
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
		{ code: 'not_lego', label: 'Not Lego' },
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

	function openPicker() {
		selectedId = committedColorId ?? predictedColorId ?? null;
		query = '';
		pickerOpen = true;
		void loadColors();
	}

	function closePicker() {
		pickerOpen = false;
	}

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
		<!-- PART verdict -->
		<div class="flex flex-wrap items-center gap-2">
			<span class="text-xs font-semibold text-ink-muted">
				Part correct?
			</span>
			<div class="flex border border-line">
				<button
					type="button"
					onclick={() => setPartVerdict(true)}
					disabled={partBusy}
					title="The predicted PART TYPE is correct (this does NOT judge the color)"
					aria-label="Mark part prediction correct"
					class="inline-flex items-center gap-1 border-r border-line px-2 py-1 text-sm transition-colors disabled:opacity-50 {partVerdict ===
					true
						? 'bg-success-soft text-success-ink'
						: 'text-ink-muted hover:text-success-ink'}"
				>
					<Check size={14} />
					Yes
				</button>
				<button
					type="button"
					onclick={() => setPartVerdict(false)}
					disabled={partBusy}
					title="The predicted PART TYPE is wrong (this does NOT judge the color)"
					aria-label="Mark part prediction wrong"
					class="inline-flex items-center gap-1 px-2 py-1 text-sm transition-colors disabled:opacity-50 {partVerdict ===
					false
						? 'bg-danger-soft text-danger-ink'
						: 'text-ink-muted hover:text-danger-ink'}"
				>
					<X size={14} />
					No
				</button>
			</div>
			{#if partBusy}
				<Spinner size={12} />
			{:else if partSent}
				<span
					class="inline-flex items-center border border-success/50 bg-success-soft px-1.5 py-0.5 text-xs font-semibold text-success-ink"
					title="This part verdict has been sent to Brickognize"
				>
					Sent
				</span>
			{/if}
			<span class="text-xs text-ink-muted">Part type only — not the color.</span>
		</div>

		<!-- COLOR verdict -->
		<div class="flex flex-col gap-1.5">
			<div class="flex flex-wrap items-center gap-2">
				<span class="text-xs font-semibold text-ink-muted">
					Color correct?
				</span>
				<!-- The predicted color, with a one-click "yes it's right". -->
				<span
					class="inline-flex items-center gap-1.5 text-sm text-ink"
					title="Brickognize predicted this color"
				>
					{#if predictedColorHex}
						<span
							class="inline-block h-3.5 w-3.5 border border-line"
							style:background-color={predictedColorHex}
						></span>
					{/if}
					<span>{predictedColorName ?? '—'}</span>
				</span>
				<button
					type="button"
					onclick={acceptPredictedColor}
					disabled={colorBusy || predictedColorId == null}
					title="The predicted color is correct"
					aria-label="Mark predicted color correct"
					class="inline-flex items-center gap-1 border border-line px-2 py-1 text-sm transition-colors disabled:opacity-50 {acceptedPrediction
						? 'bg-success-soft text-success-ink'
						: 'text-ink-muted hover:text-success-ink'}"
				>
					<Check size={14} />
					Yes
				</button>
				<!-- Or open the dropdown to submit a different, correct color. -->
				<button
					type="button"
					onclick={() => (pickerOpen ? closePicker() : openPicker())}
					title="Pick the correct color instead"
					class="inline-flex items-center gap-1.5 border px-2 py-1 text-sm transition-colors {correctedToDifferent
						? 'border-danger/50 bg-danger-soft text-danger-ink'
						: 'border-line bg-surface text-ink-muted hover:bg-hover'}"
				>
					{#if correctedToDifferent && committedColorHex}
						<span
							class="inline-block h-3.5 w-3.5 border border-line"
							style:background-color={committedColorHex}
						></span>
					{:else}
						<Search size={14} />
					{/if}
					<span>{correctedToDifferent ? committedColorName : 'No — pick color'}</span>
				</button>
				{#if colorBusy}
					<Spinner size={12} />
				{:else if colorSent}
					<span
						class="inline-flex items-center border border-success/50 bg-success-soft px-1.5 py-0.5 text-xs font-semibold text-success-ink"
						title="This color correction has been sent to Brickognize"
					>
						Sent
					</span>
				{/if}
			</div>

			{#if pickerOpen}
				<div class="flex flex-col gap-2 border border-line bg-surface p-2">
					<div class="flex items-center gap-2 border border-line bg-well px-2">
						<Search size={14} class="text-ink-muted" />
						<input
							type="search"
							bind:value={query}
							placeholder="Search colors…"
							aria-label="Search colors"
							class="w-full bg-transparent py-1.5 text-sm text-ink outline-none"
						/>
					</div>

					{#if colorsLoading && colors.length === 0}
						<div class="flex items-center gap-2 px-1 py-2 text-sm text-ink-muted">
							<Spinner size={12} /> Loading colors…
						</div>
					{:else if colorsError}
						<Alert tone="danger">{colorsError}</Alert>
					{:else}
						<div class="max-h-56 overflow-y-auto">
							{#each filteredColors as c (c.id)}
								{@const idStr = String(c.id)}
								{@const hex = swatchHex(c.rgb)}
								{@const isPrediction = idStr === predictedColorId}
								{@const isSelected = idStr === selectedId}
								<button
									type="button"
									onclick={() => chooseColor(idStr)}
									class="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm transition-colors {isSelected
										? 'bg-primary-soft text-ink'
										: 'text-ink hover:bg-hover'}"
								>
									<span
										class="inline-block h-4 w-4 flex-shrink-0 border border-line"
										style:background-color={hex ?? 'transparent'}
									></span>
									<span class="flex-1 truncate">{c.name}</span>
									{#if c.is_trans}
										<span class="text-xs text-ink-muted">trans</span>
									{/if}
									{#if isPrediction}
										<span
											class="inline-flex items-center gap-1 border border-info/60 bg-info-soft px-1.5 py-0.5 text-xs font-semibold text-info-ink"
											title="Brickognize predicted this color"
										>
											<Sparkles size={11} />
											Prediction
										</span>
									{/if}
									{#if isSelected}
										<Check size={14} class="flex-shrink-0 text-primary-ink" />
									{/if}
								</button>
							{:else}
								<div class="px-2 py-2 text-sm text-ink-muted">No colors match.</div>
							{/each}
						</div>
					{/if}

					<div class="flex items-center justify-end gap-2">
						<Button variant="ghost" size="sm" onclick={closePicker}>Cancel</Button>
						<Button
							variant="primary"
							size="sm"
							loading={colorBusy}
							disabled={!selectedId}
							onclick={confirmColor}
						>
							Confirm color
						</Button>
					</div>
				</div>
			{/if}
		</div>

		<!-- Capture-issue flags -->
		<div class="flex flex-wrap items-center gap-2">
			<span class="text-xs font-semibold text-ink-muted">
				Report issue
			</span>
			<div class="flex border border-line">
				{#each REJECTION_REASONS as reason, i (reason.code)}
					{@const active = rejectionReasons.has(reason.code)}
					<button
						type="button"
						onclick={() => toggleRejectionReason(reason.code)}
						disabled={rejectionBusy}
						aria-pressed={active}
						title={`Flag this capture: ${reason.label}`}
						class="inline-flex items-center gap-1 px-2 py-1 text-sm transition-colors disabled:opacity-50 {i <
						REJECTION_REASONS.length - 1
							? 'border-r border-line'
							: ''} {active
							? 'bg-danger-soft text-danger-ink'
							: 'text-ink-muted hover:text-danger-ink'}"
					>
						{reason.label}
					</button>
				{/each}
			</div>
			{#if rejectionBusy}
				<Spinner size={12} />
			{/if}
		</div>

		<!-- Reserve the banner's height whether or not it's showing — a success
		     message appearing after a click must not reflow the surrounding modal. -->
		<div class="mt-1 min-h-[2.75rem]">
			{#if feedback}
				<Alert tone={feedback.variant}>{feedback.text}</Alert>
			{/if}
		</div>
	</div>
{/if}
