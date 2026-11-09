<!--
	The way through the setup: Back, and the one button that goes on. When the
	step is not done yet and must be, the reason sits beside the button.
-->
<script lang="ts">
	import Button from '$lib/components/ui/Button.svelte';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import LayoutDashboard from '@lucide/svelte/icons/layout-dashboard';

	let {
		blocker,
		showBack,
		showContinue,
		finish,
		busy,
		onBack,
		onContinue
	}: {
		// Why Continue cannot go on yet, or null.
		blocker: string | null;
		showBack: boolean;
		showContinue: boolean;
		// The last step: the button opens the dashboard.
		finish: boolean;
		busy: boolean;
		onBack: () => void;
		onContinue: () => void;
	} = $props();
</script>

<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-end">
	{#if blocker && showContinue}<p class="text-sm text-ink-muted sm:mr-auto">{blocker}</p>{/if}
	<div class="flex flex-wrap items-center gap-2">
		{#if showBack}
			<Button variant="ghost" icon={ChevronLeft} onclick={onBack}>Back</Button>
		{/if}
		{#if showContinue}
			{#if finish}
				<Button variant="primary" icon={LayoutDashboard} loading={busy} onclick={onContinue}>
					Open the dashboard
				</Button>
			{:else}
				<Button variant="primary" loading={busy} disabled={!!blocker} onclick={onContinue}>
					Continue
					<ChevronRight size={16} />
				</Button>
			{/if}
		{/if}
	</div>
</div>
