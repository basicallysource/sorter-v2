<script lang="ts">
	import Button from '$lib/components/ui/Button.svelte';
	import CheckCircle2 from '@lucide/svelte/icons/circle-check';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';

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

<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-end">
	{#if blockerReason}<p class="text-sm text-ink-muted sm:mr-auto">{blockerReason}</p>{/if}
	<div class="flex flex-wrap items-center gap-2">
		{#if showBack}
			<Button variant="ghost" icon={ChevronLeft} onclick={onBack}>Back</Button>
		{/if}
		{#if showFinish}
			<Button variant="primary" icon={CheckCircle2} disabled={finishDisabled} onclick={onFinish}>
				{finishLabel}
			</Button>
		{/if}
		{#if showContinue}
			<Button variant="primary" disabled={continueDisabled} onclick={onContinue}>
				{continueLabel}
				<ChevronRight size={16} />
			</Button>
		{/if}
	</div>
</div>
