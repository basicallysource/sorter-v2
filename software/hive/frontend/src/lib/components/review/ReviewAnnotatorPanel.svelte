<script lang="ts">
	import type { AnnotatorApi } from '$lib/components/annotator-api.svelte';

	interface Props {
		annotatorApi: AnnotatorApi;
	}

	let { annotatorApi }: Props = $props();
</script>

<div class="border border-line bg-surface p-4">
	<div class="mb-3 flex items-center justify-between">
		<h2 class="text-sm font-semibold text-ink">Annotator</h2>
		<span class="text-xs font-medium {annotatorApi.isDirty ? 'text-warning-ink' : annotatorApi.hasSavedBaseline ? 'text-success-ink' : 'text-ink-muted'}">
			{#if annotatorApi.isDirty}
				Unsaved
			{:else if annotatorApi.hasSavedBaseline}
				Saved
			{:else}
				Not saved
			{/if}
		</span>
	</div>

	<div class="grid grid-cols-4 gap-1.5">
		<!-- Indirect via arrow so each click resolves the *current* annotatorApi.* binding.
			 The api fields are reassigned by SampleAnnotator's $effect on every remount
			 (e.g. when the review queue swaps in a new sample), and the binding here is
			 captured at render time — without the indirection the buttons keep calling
			 the previous sample's closures (or the default no-op stubs). -->
		<button onclick={() => annotatorApi.undo()} class="border border-line px-2 py-2 text-xs text-ink-muted hover:bg-hover">Undo</button>
		<button onclick={() => annotatorApi.redo()} class="border border-line px-2 py-2 text-xs text-ink-muted hover:bg-hover">Redo</button>
		<button
			onclick={() => annotatorApi.deleteSelected()}
			disabled={annotatorApi.selectedCount === 0}
			class="border border-primary/20 px-2 py-2 text-xs text-primary-ink transition-colors hover:bg-primary-soft disabled:cursor-not-allowed disabled:border-line disabled:text-border"
		>
			Delete
		</button>
		<button onclick={() => annotatorApi.clearAll()} class="border border-warning/30 px-2 py-2 text-xs text-warning-ink hover:bg-warning/[0.1]">Clear</button>
	</div>

	<div class="mt-3 inline-flex border border-line bg-well p-1">
		<button
			type="button"
			onclick={() => { annotatorApi.activeTool = 'rectangle'; }}
			class="px-3 py-1.5 text-xs font-medium transition-colors {annotatorApi.activeTool === 'rectangle' ? 'bg-text text-surface' : 'text-ink-muted hover:bg-surface'}"
		>
			Rectangle
		</button>
		<button
			type="button"
			onclick={() => { annotatorApi.activeTool = 'polygon'; }}
			class="px-3 py-1.5 text-xs font-medium transition-colors {annotatorApi.activeTool === 'polygon' ? 'bg-text text-surface' : 'text-ink-muted hover:bg-surface'}"
		>
			Polygon
		</button>
	</div>

	<div class="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
		<div class="bg-well px-2 py-2">
			<div class="text-sm font-semibold text-ink">{annotatorApi.totalAnnotations}</div>
			<div class="text-ink-muted">Total</div>
		</div>
		<div class="bg-well px-2 py-2">
			<div class="text-sm font-semibold text-ink">{annotatorApi.seededCount}</div>
			<div class="text-ink-muted">Seeded</div>
		</div>
		<div class="bg-well px-2 py-2">
			<div class="text-sm font-semibold text-ink">{annotatorApi.manualCount}</div>
			<div class="text-ink-muted">Manual</div>
		</div>
	</div>

	<div class="mt-3 flex gap-2">
		<button
			type="button"
			onclick={() => annotatorApi.revert()}
			class="flex-1 border border-line px-3 py-2 text-xs font-medium text-ink-muted hover:bg-hover"
		>
			Revert
		</button>
		{#if annotatorApi.hasSeedBoxes}
			<button
				type="button"
				onclick={() => annotatorApi.loadSorterBoxes()}
				class="flex-1 border border-line px-3 py-2 text-xs font-medium text-ink-muted hover:bg-hover"
			>
				Reset
			</button>
		{/if}
	</div>

	{#if annotatorApi.feedback}
		<p class="mt-3 px-3 py-2 text-xs {annotatorApi.feedbackTone === 'danger' ? 'bg-primary/8 text-primary-ink' : annotatorApi.feedbackTone === 'success' ? 'bg-success/10 text-success-ink' : 'bg-well text-ink-muted'}">
			{annotatorApi.feedback}
		</p>
	{/if}

	<button
		type="button"
		onclick={() => annotatorApi.save()}
		disabled={annotatorApi.saving || !annotatorApi.isDirty}
		class="mt-3 flex w-full items-center justify-center px-3 py-2 text-xs font-medium text-white transition-colors disabled:cursor-not-allowed disabled:bg-primary/40 {annotatorApi.saving || !annotatorApi.isDirty ? 'bg-primary/40' : 'bg-primary hover:bg-primary-hover'}"
	>
		{annotatorApi.saving ? 'Saving...' : 'Save Annotations'}
	</button>
</div>
