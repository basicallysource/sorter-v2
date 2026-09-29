<script lang="ts">
	import Crosshair from '@lucide/svelte/icons/crosshair';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';

	let {
		sectionCount,
		columnEnabled,
		sectionBusyKey,
		pointingKey,
		toggleDisabled,
		pointDisabled,
		onToggleColumn,
		onPointSection
	}: {
		sectionCount: number;
		columnEnabled: (sectionIndex: number) => boolean;
		sectionBusyKey: string | null;
		pointingKey: string | null;
		toggleDisabled: boolean;
		pointDisabled: boolean;
		onToggleColumn: (sectionIndex: number, enabled: boolean) => void;
		onPointSection: (sectionIndex: number) => void;
	} = $props();
</script>

<Panel
	title="Sections across all layers"
	description="Turn a section off here to stop sorting into it on every layer at once, or point the chute at it to find it. Each layer also has its own section controls below."
>
	<div class="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap">
		{#each Array(sectionCount) as _unused, sectionIndex}
			{@const colOn = columnEnabled(sectionIndex)}
			<div class="flex items-center gap-3 rounded-control bg-well py-1 pr-1.5 pl-3">
				<span class="mr-auto text-sm font-medium {colOn ? 'text-ink' : 'text-ink-muted'}">
					Section {sectionIndex + 1}
				</span>
				<Switch
					checked={colOn}
					label={colOn
						? `Turn off section ${sectionIndex + 1} on all layers`
						: `Turn on section ${sectionIndex + 1} on all layers`}
					disabled={toggleDisabled}
					onchange={() => onToggleColumn(sectionIndex, !colOn)}
				/>
				{#if sectionBusyKey === `col-${sectionIndex}`}
					<Spinner size={14} class="text-primary-ink" />
				{/if}
				<Button
					size="sm"
					variant="ghost"
					icon={Crosshair}
					label="Point the chute at section {sectionIndex + 1}"
					loading={pointingKey === `point-${sectionIndex}`}
					disabled={pointDisabled}
					onclick={() => onPointSection(sectionIndex)}
				/>
			</div>
		{/each}
	</div>
</Panel>
