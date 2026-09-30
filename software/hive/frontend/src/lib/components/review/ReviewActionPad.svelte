<script lang="ts">
	import { FEATURES } from '$lib/features';
	import Button from '$lib/components/Button.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import PenLine from '@lucide/svelte/icons/pen-line';

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

<Panel title="Your call" flush>
	<div class="flex flex-col gap-3 px-(--pad-panel) pb-(--pad-panel)">
		{#if FEATURES.ANNOTATION_EDITING}
			<div class="flex flex-wrap gap-2">
				<Button size="sm" icon={PenLine} disabled={loading || submitting} title="D" onclick={onToggleAnnotate}
					>{annotateMode ? 'Stop annotating' : 'Annotate'}</Button
				>
				{#if annotateMode}
					<Button size="sm" variant="ghost" disabled={loading || submitting} title="Escape" onclick={onExitAnnotate}>Close</Button>
				{/if}
			</div>
		{/if}

		<!-- Laid out like the arrow keys that do the same. -->
		<div class="grid grid-cols-3 gap-2">
			<Button class="col-start-2 w-full" variant="primary" icon={ArrowUp} disabled={loading || submitting} onclick={onAccept}
				>Accept</Button
			>
			<Button class="col-start-1 w-full" variant="ghost" icon={ArrowLeft} disabled={reviewHistoryLength === 0 || loading || submitting} onclick={onBack}
				>Back</Button
			>
			<Button class="w-full" icon={ArrowDown} disabled={loading || submitting} onclick={onReject}>Reject</Button>
			<Button class="w-full" variant="ghost" icon={ArrowRight} disabled={loading || submitting} onclick={onSkip}>Skip</Button>
		</div>

		<p class="text-sm text-ink-muted">
			The arrow keys do the same{#if reviewHistoryLength > 0}; <span class="num">{reviewHistoryLength}</span> reviewed this session{/if}.
		</p>
	</div>
</Panel>
