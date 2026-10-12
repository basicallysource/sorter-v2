<!--
	docs/components.md#color-review. The review of one classified piece, in
	three questions: is the part right, is the color right, and is anything
	wrong with the capture. Each question is a row with its name on the left
	and its answer on the right, divided by lines; where the block is narrow
	the name sits above the answer.

	The color row shows the predicted color with Yes and "No, pick the
	color". No opens the colors right under it (`ColorChoice`: the likely
	colors first, then every color); a pick is staged and Confirm saves it,
	Cancel closes it. Once a different color is saved, the No button names
	it. With no predicted color there is no Yes, only "Pick the color".

	Every answer is a callback; the app saves it and passes the state back
	(`partVerdict`, `correctedId`, `activeIssues`, the busy and sent flags).
	`oncolor` resolves true when the color was saved, which closes the
	colors. `onpicking` says when the colors open, so the app can fetch the
	ranking then. `notice` is a warning or a failure to show under the rows.

	<PieceReview {palette} {likely} predicted={orange} predictedMark="Predicted 82%"
		partVerdict={verdict} correctedId={corrected} issues={REASONS} activeIssues={flags}
		onpart={savePart} oncolor={saveColor} onissue={toggleIssue} />
-->
<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import Pipette from '@lucide/svelte/icons/pipette';
	import Alert from './Alert.svelte';
	import Badge from './Badge.svelte';
	import Button from './Button.svelte';
	import ColorChoice, { type LikelyColor, type PaletteColor } from './ColorChoice.svelte';
	import SegmentedControl from './SegmentedControl.svelte';
	import Spinner from './Spinner.svelte';
	import { swatchColor } from './ColorChip.svelte';

	let {
		partVerdict = null,
		partSent = false,
		partBusy = false,
		predicted = null,
		predictedMark = 'Predicted',
		correctedId = null,
		colorSent = false,
		colorBusy = false,
		palette,
		likely = null,
		likelyNote = null,
		issues,
		activeIssues = [],
		issuesBusy = false,
		notice = null,
		onpart,
		oncolor,
		onissue,
		onpicking
	}: {
		partVerdict?: boolean | null;
		partSent?: boolean;
		partBusy?: boolean;
		// The color the piece was given; null when none was predicted.
		predicted?: PaletteColor | null;
		// What marks it among the colors ("Predicted 82%").
		predictedMark?: string;
		// The color saved as the true one, if any.
		correctedId?: number | null;
		colorSent?: boolean;
		colorBusy?: boolean;
		palette: PaletteColor[];
		likely?: LikelyColor[] | null;
		likelyNote?: string | null;
		issues: { code: string; label: string }[];
		activeIssues?: string[];
		issuesBusy?: boolean;
		notice?: { tone: 'warning' | 'danger'; text: string } | null;
		onpart: (correct: boolean) => void;
		oncolor: (id: number) => boolean | Promise<boolean>;
		onissue: (code: string) => void;
		onpicking?: (open: boolean) => void;
	} = $props();

	let picking = $state(false);
	let staged = $state<number | null>(null);

	const corrected = $derived(
		correctedId == null ? null : (palette.find((c) => c.id === correctedId) ?? null)
	);
	const acceptedPrediction = $derived(predicted != null && correctedId === predicted.id);
	const correctedToOther = $derived(correctedId != null && correctedId !== predicted?.id);
	const stagedColor = $derived(
		staged == null ? null : (palette.find((c) => c.id === staged) ?? null)
	);
	const marks = $derived<Record<number, string>>(
		predicted ? { [predicted.id]: predictedMark } : {}
	);
	const active = $derived(new Set(activeIssues));

	function openColors() {
		staged = correctedToOther ? correctedId : null;
		picking = true;
		onpicking?.(true);
	}

	function closeColors() {
		picking = false;
		onpicking?.(false);
	}

	async function confirmColor() {
		if (staged == null) return;
		if (await oncolor(staged)) closeColors();
	}

	const row = 'grid gap-x-6 gap-y-2 py-5 first:pt-0 last:pb-0 @xl:grid-cols-[9rem_minmax(0,1fr)]';
	const name = 'text-sm font-medium text-ink @xl:flex @xl:h-(--size-control-sm) @xl:items-center';
</script>

<div class="@container flex flex-col">
	<div class="flex flex-col divide-y divide-line">
		<!-- The part: only its type, never its color -->
		<div class={row}>
			<div class={name}>Part correct?</div>
			<div class="flex min-w-0 flex-col gap-2">
				<div class="flex flex-wrap items-center gap-3">
					<SegmentedControl
						label="Is the predicted part right?"
						size="sm"
						value={partVerdict === true ? 'yes' : partVerdict === false ? 'no' : ''}
						options={[
							{ value: 'yes', label: 'Yes' },
							{ value: 'no', label: 'No' }
						]}
						onchange={(verdict) => onpart(verdict === 'yes')}
					/>
					{#if partBusy}<Spinner size={14} />{:else if partSent}<Badge tone="success">Sent</Badge
						>{/if}
				</div>
				<p class="text-sm text-ink-muted">The part type only; the color is the next question.</p>
			</div>
		</div>

		<!-- The color: yes, or pick it from the likely colors -->
		<div class={row}>
			<div class={name}>Color correct?</div>
			<div class="flex min-w-0 flex-col gap-4">
				<div class="flex flex-wrap items-center gap-2">
					{#if predicted}
						<span class="mr-1 inline-flex min-w-0 items-center gap-2 text-sm text-ink">
							<span
								aria-hidden="true"
								class="size-5 shrink-0 rounded-check border border-line-strong"
								style:background-color={swatchColor(predicted.rgb)}
							></span>
							<span class="truncate">{predicted.name}</span>
						</span>
						<Button
							size="sm"
							variant={acceptedPrediction ? 'primary' : 'secondary'}
							icon={Check}
							disabled={colorBusy}
							onclick={() => {
								closeColors();
								void oncolor(predicted.id);
							}}
						>
							Yes
						</Button>
					{:else}
						<span class="mr-1 text-sm text-ink-muted">No color was predicted.</span>
					{/if}
					<Button
						size="sm"
						variant={picking || correctedToOther ? 'primary' : 'secondary'}
						icon={correctedToOther ? undefined : Pipette}
						aria-expanded={picking}
						onclick={picking ? closeColors : openColors}
					>
						{#if correctedToOther && corrected}
							<span
								aria-hidden="true"
								class="size-4 shrink-0 rounded-check border border-line-strong"
								style:background-color={swatchColor(corrected.rgb)}
							></span>
							No, it is {corrected.name}
						{:else}
							{predicted ? 'No, pick the color' : 'Pick the color'}
						{/if}
					</Button>
					{#if colorBusy}<Spinner size={14} />{:else if colorSent}<Badge tone="success">Sent</Badge
						>{/if}
				</div>

				{#if picking}
					<ColorChoice
						{palette}
						{likely}
						value={staged}
						{marks}
						note={likelyNote}
						disabled={colorBusy}
						onpick={(id) => (staged = id)}
					/>
					<div class="flex flex-wrap items-center justify-end gap-2">
						<Button variant="ghost" size="sm" onclick={closeColors}>Cancel</Button>
						<Button
							variant="primary"
							size="sm"
							loading={colorBusy}
							disabled={staged == null}
							onclick={confirmColor}
						>
							{stagedColor ? `Confirm ${stagedColor.name}` : 'Confirm the color'}
						</Button>
					</div>
				{/if}
			</div>
		</div>

		<!-- The capture: any number of these can apply -->
		<div class={row}>
			<div class={name}>Report an issue</div>
			<div class="flex min-w-0 flex-col gap-2">
				<div class="flex flex-wrap items-center gap-2">
					{#each issues as issue (issue.code)}
						{@const on = active.has(issue.code)}
						<Button
							size="sm"
							variant={on ? 'primary' : 'secondary'}
							icon={on ? Check : undefined}
							aria-pressed={on}
							disabled={issuesBusy}
							onclick={() => onissue(issue.code)}
						>
							{issue.label}
						</Button>
					{/each}
					{#if issuesBusy}<Spinner size={14} />{/if}
				</div>
				<p class="text-sm text-ink-muted">Any that apply to the photos.</p>
			</div>
		</div>
	</div>

	{#if notice}
		<Alert tone={notice.tone} class="mt-5">{notice.text}</Alert>
	{/if}
</div>
