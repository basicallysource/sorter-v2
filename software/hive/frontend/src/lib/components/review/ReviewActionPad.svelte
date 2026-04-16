<script lang="ts">
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

<div class="border border-border bg-white p-4">
	<div class="space-y-2 text-xs">
		<div class="flex items-center justify-center gap-2">
			<button
				type="button"
				onclick={onToggleAnnotate}
				disabled={loading || submitting}
				class="inline-flex items-center gap-2 border px-2.5 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 {annotateMode ? 'border-info/30 bg-info/10' : 'border-info/20 bg-[#F0F7FF] hover:bg-info/15'}"
			>
				<div class="border border-info/30 bg-white px-2 py-1 text-[11px] font-bold text-info">
					D
				</div>
				<div>
					<div class="font-medium text-info">Annotate</div>
					<div class="text-[11px] text-info">Toggle edit mode</div>
				</div>
			</button>
			<button
				type="button"
				onclick={onExitAnnotate}
				disabled={!annotateMode || loading || submitting}
				class="inline-flex items-center gap-2 border border-border bg-bg px-2.5 py-2 text-left transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				<div class="border border-border bg-white px-2 py-1 text-[11px] font-bold text-text">
					Esc
				</div>
				<div>
					<div class="font-medium text-text">Close</div>
					<div class="text-[11px] text-text-muted">Exit annotate</div>
				</div>
			</button>
		</div>

		<div class="mx-auto grid max-w-[210px] grid-cols-3 gap-1.5">
			<div></div>
			<button
				type="button"
				onclick={onAccept}
				disabled={loading || submitting}
				class="border border-success/20 bg-[#F0F9F5] px-3 py-3 text-center transition-colors hover:bg-success/15 disabled:cursor-not-allowed disabled:opacity-50"
			>
				<div class="text-2xl font-bold text-success">↑</div>
				<div class="mt-0.5 font-medium text-success">Accept</div>
			</button>
			<div></div>

			<button
				type="button"
				onclick={onBack}
				disabled={reviewHistoryLength === 0 || loading || submitting}
				class="border border-border bg-bg px-2 py-2 text-center transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				<div class="text-xl font-bold text-text">←</div>
				<div class="mt-0.5 font-medium text-text">Back</div>
			</button>
			<button
				type="button"
				onclick={onReject}
				disabled={loading || submitting}
				class="border border-primary/20 bg-primary-light px-3 py-3 text-center transition-colors hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
			>
				<div class="text-2xl font-bold text-primary">↓</div>
				<div class="mt-0.5 font-medium text-primary">Reject</div>
			</button>
			<button
				type="button"
				onclick={onSkip}
				disabled={loading || submitting}
				class="border border-border bg-bg px-2 py-2 text-center transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				<div class="text-xl font-bold text-text">→</div>
				<div class="mt-0.5 font-medium text-text">Skip</div>
			</button>
		</div>

		<p class="text-center text-[11px] text-text-muted">
			Green means keep it, red means reject it, and gray moves through the queue.
		</p>
		{#if reviewHistoryLength > 0}
			<p class="mt-2 text-center text-xs text-text-muted">{reviewHistoryLength} reviewed this session</p>
		{/if}
	</div>
</div>
