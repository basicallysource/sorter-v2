<script lang="ts">
	import type { AnnotatorApi } from '$lib/components/annotator-api.svelte';

	interface Props {
		annotatorApi: AnnotatorApi;
	}

	let { annotatorApi }: Props = $props();
</script>

<div class="border border-border bg-white p-4">
	<div class="mb-3 flex items-center justify-between">
		<h2 class="text-sm font-semibold text-text">Annotator</h2>
		<span class="text-xs font-medium {annotatorApi.isDirty ? 'text-[#A16207]' : annotatorApi.hasSavedBaseline ? 'text-success' : 'text-text-muted'}">
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
		<button onclick={annotatorApi.undo} class="border border-border px-2 py-2 text-[11px] text-text-muted hover:bg-bg">Undo</button>
		<button onclick={annotatorApi.redo} class="border border-border px-2 py-2 text-[11px] text-text-muted hover:bg-bg">Redo</button>
		<button
			onclick={annotatorApi.deleteSelected}
			disabled={annotatorApi.selectedCount === 0}
			class="border border-primary/20 px-2 py-2 text-[11px] text-primary transition-colors hover:bg-primary-light disabled:cursor-not-allowed disabled:border-border disabled:text-border"
		>
			Delete
		</button>
		<button onclick={annotatorApi.clearAll} class="border border-warning/30 px-2 py-2 text-[11px] text-[#A16207] hover:bg-warning/[0.1]">Clear</button>
	</div>

	<div class="mt-3 inline-flex border border-border bg-bg p-1">
		<button
			type="button"
			onclick={() => { annotatorApi.activeTool = 'rectangle'; }}
			class="px-3 py-1.5 text-xs font-medium transition-colors {annotatorApi.activeTool === 'rectangle' ? 'bg-text text-white' : 'text-text-muted hover:bg-white'}"
		>
			Rectangle
		</button>
		<button
			type="button"
			onclick={() => { annotatorApi.activeTool = 'polygon'; }}
			class="px-3 py-1.5 text-xs font-medium transition-colors {annotatorApi.activeTool === 'polygon' ? 'bg-text text-white' : 'text-text-muted hover:bg-white'}"
		>
			Polygon
		</button>
	</div>

	<div class="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
		<div class="bg-bg px-2 py-2">
			<div class="text-sm font-semibold text-text">{annotatorApi.totalAnnotations}</div>
			<div class="text-text-muted">Total</div>
		</div>
		<div class="bg-bg px-2 py-2">
			<div class="text-sm font-semibold text-text">{annotatorApi.seededCount}</div>
			<div class="text-text-muted">Seeded</div>
		</div>
		<div class="bg-bg px-2 py-2">
			<div class="text-sm font-semibold text-text">{annotatorApi.manualCount}</div>
			<div class="text-text-muted">Manual</div>
		</div>
	</div>

	<div class="mt-3 flex gap-2">
		<button
			type="button"
			onclick={annotatorApi.revert}
			class="flex-1 border border-border px-3 py-2 text-xs font-medium text-text-muted hover:bg-bg"
		>
			Revert
		</button>
		{#if annotatorApi.hasSeedBoxes}
			<button
				type="button"
				onclick={annotatorApi.loadSorterBoxes}
				class="flex-1 border border-border px-3 py-2 text-xs font-medium text-text-muted hover:bg-bg"
			>
				Reset
			</button>
		{/if}
	</div>

	{#if annotatorApi.feedback}
		<p class="mt-3 px-3 py-2 text-xs {annotatorApi.feedbackTone === 'danger' ? 'bg-primary/8 text-primary' : annotatorApi.feedbackTone === 'success' ? 'bg-success/10 text-success' : 'bg-bg text-text-muted'}">
			{annotatorApi.feedback}
		</p>
	{/if}

	<button
		type="button"
		onclick={annotatorApi.save}
		disabled={annotatorApi.saving || !annotatorApi.isDirty}
		class="mt-3 flex w-full items-center justify-center px-3 py-2 text-xs font-medium text-white transition-colors disabled:cursor-not-allowed disabled:bg-primary/40 {annotatorApi.saving || !annotatorApi.isDirty ? 'bg-primary/40' : 'bg-primary hover:bg-primary-hover'}"
	>
		{annotatorApi.saving ? 'Saving...' : 'Save Annotations'}
	</button>
</div>
