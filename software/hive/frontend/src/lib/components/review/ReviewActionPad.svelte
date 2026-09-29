<script lang="ts">
	import { FEATURES } from '$lib/features';

	interface Props {
		annotateMode: boolean;
		loading: boolean;
		submitting: boolean;
		reviewHistoryLength: number;
		onToggleAnnotate: () => void;
		onExitAnnotate: () => void;
		onAccept: () => void;
		onReject: () => void;
		onSkip: () => void;
		onBack: () => void;
	}

	let {
		annotateMode,
		loading,
		submitting,
		reviewHistoryLength,
		onToggleAnnotate,
		onExitAnnotate,
		onAccept,
		onReject,
		onSkip,
		onBack
	}: Props = $props();
</script>

<div class="border border-line bg-surface p-4">
	<div class="space-y-2 text-xs">
		{#if FEATURES.ANNOTATION_EDITING}
			<div class="flex flex-wrap items-center justify-center gap-2">
				<button
					type="button"
					onclick={onToggleAnnotate}
					disabled={loading || submitting}
					class="inline-flex items-center gap-2 border px-2.5 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 {annotateMode ? 'border-info/30 bg-info/10' : 'border-info/20 bg-info/10 hover:bg-info/15'}"
				>
					<div class="border border-info/30 bg-surface px-2 py-1 text-xs font-bold text-info-ink">
						D
					</div>
					<div>
						<div class="font-medium text-info-ink">Annotate</div>
						<div class="text-xs text-info-ink">Toggle edit mode</div>
					</div>
				</button>
				<button
					type="button"
					onclick={onExitAnnotate}
					disabled={!annotateMode || loading || submitting}
					class="inline-flex items-center gap-2 border border-line bg-well px-2.5 py-2 text-left transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
				>
					<div class="border border-line bg-surface px-2 py-1 text-xs font-bold text-ink">
						Esc
					</div>
					<div>
						<div class="font-medium text-ink">Close</div>
						<div class="text-xs text-ink-muted">Exit annotate</div>
					</div>
				</button>
			</div>
		{/if}

		<div class="mx-auto grid max-w-[210px] grid-cols-3 gap-1.5">
			<div></div>
			<button
				type="button"
				onclick={onAccept}
				disabled={loading || submitting}
				class="border border-success/20 bg-success/10 px-3 py-3 text-center transition-colors hover:bg-success/15 disabled:cursor-not-allowed disabled:opacity-50"
			>
				<div class="text-2xl font-bold text-success-ink">↑</div>
				<div class="mt-0.5 font-medium text-success-ink">Accept</div>
			</button>
			<div></div>

			<button
				type="button"
				onclick={onBack}
				disabled={reviewHistoryLength === 0 || loading || submitting}
				class="border border-line bg-well px-2 py-2 text-center transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
			>
				<div class="text-xl font-bold text-ink">←</div>
				<div class="mt-0.5 font-medium text-ink">Back</div>
			</button>
			<button
				type="button"
				onclick={onReject}
				disabled={loading || submitting}
				class="border border-primary/20 bg-primary-soft px-3 py-3 text-center transition-colors hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
			>
				<div class="text-2xl font-bold text-primary-ink">↓</div>
				<div class="mt-0.5 font-medium text-primary-ink">Reject</div>
			</button>
			<button
				type="button"
				onclick={onSkip}
				disabled={loading || submitting}
				class="border border-line bg-well px-2 py-2 text-center transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
			>
				<div class="text-xl font-bold text-ink">→</div>
				<div class="mt-0.5 font-medium text-ink">Skip</div>
			</button>
		</div>

		<p class="text-center text-xs text-ink-muted">
			Green means keep it, red means reject it, and gray moves through the queue.
		</p>
		{#if reviewHistoryLength > 0}
			<p class="mt-2 text-center text-xs text-ink-muted">{reviewHistoryLength} reviewed this session</p>
		{/if}
	</div>
</div>
