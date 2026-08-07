<script lang="ts">
	import type { Snippet } from 'svelte';
	import { RotateCcw } from 'lucide-svelte';
	import { InfoTip, Tooltip } from '$lib/components/primitives';

	// One setting: label, an info icon explaining it, and the control (passed as
	// children). The general "changed from default" concept for every settings
	// surface: when `changed` is true the row is tinted and a revert button
	// appears that resets the value back to its default. Used by every tuning
	// page (via TuningParamRow) and the root settings page.
	let {
		label,
		description,
		forId,
		changed = false,
		defaultLabel,
		onRevert,
		children
	}: {
		label: string;
		description?: string;
		forId?: string;
		changed?: boolean;
		defaultLabel?: string;
		onRevert?: () => void;
		children: Snippet;
	} = $props();
</script>

<div
	class="flex items-center justify-between gap-3 border px-3 py-2.5 transition-colors {changed
		? 'border-warning/50 bg-warning/[0.06]'
		: 'border-border bg-bg'}"
>
	<label class="flex min-w-0 items-center gap-1.5 text-sm font-medium text-text" for={forId}>
		<span class="min-w-0">{label}</span>
		{#if description}
			<InfoTip text={description} />
		{/if}
	</label>
	<div class="flex shrink-0 items-center gap-2">
		{#if changed && onRevert}
			<Tooltip text="Reset to default{defaultLabel !== undefined ? `: ${defaultLabel}` : ''}">
				<button
					type="button"
					onclick={onRevert}
					aria-label="Reset to default{defaultLabel !== undefined ? `: ${defaultLabel}` : ''}"
					class="inline-flex items-center border border-transparent p-1 text-warning transition-colors hover:border-border hover:text-text"
				>
					<RotateCcw size={15} />
				</button>
			</Tooltip>
		{/if}
		{@render children()}
	</div>
</div>
