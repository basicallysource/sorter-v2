<script lang="ts">
	import type { AnnotatorApi } from '$lib/components/annotator-api.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Check from '@lucide/svelte/icons/check';
	import Redo2 from '@lucide/svelte/icons/redo-2';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Undo2 from '@lucide/svelte/icons/undo-2';
	import X from '@lucide/svelte/icons/x';

	interface Props {
		annotatorApi: AnnotatorApi;
	}

	let { annotatorApi }: Props = $props();
</script>

<Panel title="Annotator" flush>
	{#snippet actions()}
		<Badge tone={annotatorApi.isDirty ? 'warning' : annotatorApi.hasSavedBaseline ? 'success' : 'neutral'}>
			{annotatorApi.isDirty ? 'Unsaved' : annotatorApi.hasSavedBaseline ? 'Saved' : 'Not saved'}
		</Badge>
	{/snippet}
	<div class="flex flex-col gap-3 px-(--pad-panel) pb-(--pad-panel)">
		<div class="flex flex-wrap gap-1">
			<Button size="sm" icon={Undo2} onclick={() => annotatorApi.undo()}>Undo</Button>
			<Button size="sm" icon={Redo2} onclick={() => annotatorApi.redo()}>Redo</Button>
			<Button size="sm" icon={Trash2} disabled={annotatorApi.selectedCount === 0} onclick={() => annotatorApi.deleteSelected()}
				>Delete</Button
			>
			<Button size="sm" icon={X} onclick={() => annotatorApi.clearAll()}>Clear all</Button>
		</div>
		<SegmentedControl
			label="Tool"
			size="sm"
			value={annotatorApi.activeTool}
			options={[
				{ value: 'rectangle', label: 'Rectangle' },
				{ value: 'polygon', label: 'Polygon' }
			]}
			onchange={(tool) => (annotatorApi.activeTool = tool)}
		/>
		<div class="flex flex-wrap gap-1">
			<Button size="sm" variant="ghost" title="Back to the last saved state" onclick={() => annotatorApi.revert()}>Cancel</Button>
			{#if annotatorApi.hasSeedBoxes}
				<Button size="sm" variant="ghost" icon={RotateCcw} title="Back to the machine's own boxes" onclick={() => annotatorApi.loadSorterBoxes()}
					>Reset</Button
				>
			{/if}
		</div>
		<div class="grid grid-cols-3 gap-1 text-center">
			{#each [['Total', annotatorApi.totalAnnotations], ['Seeded', annotatorApi.seededCount], ['Manual', annotatorApi.manualCount]] as [name, count] (name)}
				<div class="rounded-control bg-well py-1.5">
					<div class="num text-sm font-semibold text-ink">{count}</div>
					<div class="text-sm text-ink-muted">{name}</div>
				</div>
			{/each}
		</div>
		{#if annotatorApi.feedback}
			<Alert tone={annotatorApi.feedbackTone === 'danger' ? 'danger' : annotatorApi.feedbackTone === 'success' ? 'success' : 'info'}
				>{annotatorApi.feedback}</Alert
			>
		{/if}
	</div>
	{#snippet footer()}
		<Button variant="primary" size="sm" icon={Check} loading={annotatorApi.saving} disabled={!annotatorApi.isDirty} onclick={() => annotatorApi.save()}
			>Save the annotations</Button
		>
	{/snippet}
</Panel>
