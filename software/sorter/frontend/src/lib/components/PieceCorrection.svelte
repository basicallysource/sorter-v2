<script lang="ts">
	import { Check, X, Search, Sparkles } from 'lucide-svelte';
	import { Button, Alert } from '$lib/components/primitives';
	import Spinner from '$lib/components/Spinner.svelte';
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

	async function confirmColor() {
		if (colorBusy || !selectedId) return;
		colorBusy = true;
		feedback = null;
		try {
			const resp = await postCorrection({ color_corrected_id: selectedId, submit: true });
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

	// The color currently shown on the trigger button: the committed correction
	// if any, otherwise the Brickognize prediction.
	const shownColorId = $derived(committedColorId ?? predictedColorId);
	const shownColorName = $derived(colorNameFor(shownColorId) ?? piece.color_name ?? null);
	const shownColorHex = $derived(swatchHex(colorRgbFor(shownColorId)));

	const gap = $derived(compact ? 'gap-2' : 'gap-3');
</script>

{#if piece.correctable}
	<div class="flex flex-col {gap}">
		<!-- PART verdict -->
		<div class="flex flex-wrap items-center gap-2">
			<span class="text-xs font-semibold tracking-wider text-text-muted uppercase">
				Part correct?
			</span>
			<div class="flex border border-border">
				<button
					type="button"
					onclick={() => setPartVerdict(true)}
					disabled={partBusy}
					title="The predicted PART TYPE is correct (this does NOT judge the color)"
					aria-label="Mark part prediction correct"
					class="inline-flex items-center gap-1 border-r border-border px-2 py-1 text-sm transition-colors disabled:opacity-50 {partVerdict ===
					true
						? 'bg-success/15 text-success'
						: 'text-text-muted hover:text-success'}"
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
						? 'bg-danger/15 text-danger'
						: 'text-text-muted hover:text-danger'}"
				>
					<X size={14} />
					No
				</button>
			</div>
			{#if partBusy}
				<Spinner size={12} />
			{:else if partSent}
				<span
					class="inline-flex items-center border border-success/50 bg-success/[0.12] px-1.5 py-0.5 text-xs font-semibold tracking-wider text-success uppercase"
					title="This part verdict has been sent to Brickognize"
				>
					Sent
				</span>
			{/if}
			<span class="text-xs text-text-muted">Part type only — not the color.</span>
		</div>

		<!-- COLOR verdict -->
		<div class="flex flex-col gap-1.5">
			<div class="flex flex-wrap items-center gap-2">
				<span class="text-xs font-semibold tracking-wider text-text-muted uppercase">
					True color
				</span>
				<button
					type="button"
					onclick={() => (pickerOpen ? closePicker() : openPicker())}
					class="inline-flex items-center gap-1.5 border border-border bg-surface px-2 py-1 text-sm text-text transition-colors hover:bg-bg"
				>
					{#if shownColorHex}
						<span
							class="inline-block h-3.5 w-3.5 border border-border"
							style:background-color={shownColorHex}
						></span>
					{/if}
					<span>{shownColorName ?? 'Pick a color'}</span>
				</button>
				{#if committedColorId}
					{#if colorSent}
						<span
							class="inline-flex items-center border border-success/50 bg-success/[0.12] px-1.5 py-0.5 text-xs font-semibold tracking-wider text-success uppercase"
							title="This color correction has been sent to Brickognize"
						>
							Sent
						</span>
					{:else}
						<span
							class="inline-flex items-center border border-border bg-surface px-1.5 py-0.5 text-xs font-semibold tracking-wider text-text-muted uppercase"
						>
							Locked in
						</span>
					{/if}
				{/if}
			</div>

			{#if pickerOpen}
				<div class="flex flex-col gap-2 border border-border bg-surface p-2">
					<div class="flex items-center gap-2 border border-border bg-bg px-2">
						<Search size={14} class="text-text-muted" />
						<input
							type="search"
							bind:value={query}
							placeholder="Search colors…"
							aria-label="Search colors"
							class="w-full bg-transparent py-1.5 text-sm text-text outline-none"
						/>
					</div>

					{#if colorsLoading && colors.length === 0}
						<div class="flex items-center gap-2 px-1 py-2 text-sm text-text-muted">
							<Spinner size={12} /> Loading colors…
						</div>
					{:else if colorsError}
						<Alert variant="danger">{colorsError}</Alert>
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
										? 'bg-primary/15 text-text'
										: 'text-text hover:bg-bg'}"
								>
									<span
										class="inline-block h-4 w-4 flex-shrink-0 border border-border"
										style:background-color={hex ?? 'transparent'}
									></span>
									<span class="flex-1 truncate">{c.name}</span>
									{#if c.is_trans}
										<span class="text-xs text-text-muted">trans</span>
									{/if}
									{#if isPrediction}
										<span
											class="inline-flex items-center gap-1 border border-info/60 bg-info/[0.12] px-1.5 py-0.5 text-xs font-semibold tracking-wider text-info uppercase"
											title="Brickognize predicted this color"
										>
											<Sparkles size={11} />
											Prediction
										</span>
									{/if}
									{#if isSelected}
										<Check size={14} class="flex-shrink-0 text-primary" />
									{/if}
								</button>
							{:else}
								<div class="px-2 py-2 text-sm text-text-muted">No colors match.</div>
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

		{#if feedback}
			<Alert variant={feedback.variant}>{feedback.text}</Alert>
		{/if}
	</div>
{/if}
