<script lang="ts">
	import { CheckCircle2, ChevronLeft, ChevronRight } from 'lucide-svelte';

	let {
		blockerReason,
		showBack,
		showFinish,
		showContinue,
		continueDisabled,
		continueLabel,
		finishDisabled,
		finishLabel,
		onBack,
		onFinish,
		onContinue
	}: {
		blockerReason: string | null;
		showBack: boolean;
		showFinish: boolean;
		showContinue: boolean;
		continueDisabled: boolean;
		continueLabel: string;
		finishDisabled: boolean;
		finishLabel: string;
		onBack: () => void;
		onFinish: () => void;
		onContinue: () => void;
	} = $props();
</script>

<div
	class="mt-6 flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-end"
>
	{#if blockerReason}
		<p class="text-xs text-text-muted">{blockerReason}</p>
	{/if}
	<div class="flex flex-wrap items-center gap-2">
		{#if showBack}
			<button
				onclick={onBack}
				class="setup-button-secondary inline-flex items-center gap-2 px-3 py-2 text-sm text-text transition-colors"
			>
				<ChevronLeft size={14} />
				Back
			</button>
		{/if}

		{#if showFinish}
			<button
				onclick={onFinish}
				disabled={finishDisabled}
				class="inline-flex items-center gap-2 border border-success bg-success px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-60"
			>
				<CheckCircle2 size={14} />
				{finishLabel}
			</button>
		{/if}

		{#if showContinue}
			<button
				onclick={onContinue}
				disabled={continueDisabled}
				class="setup-button-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
			>
				{continueLabel}
				<ChevronRight size={14} />
			</button>
		{/if}
	</div>
</div>
