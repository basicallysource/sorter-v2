<script lang="ts">
	// One setting, drawn as the design system's SettingRow (its name and a
	// sentence on the left, the control on the right, in a divide-y list in a
	// flush panel), plus what the system's row lacks yet: when `changed`, a
	// "Changed" badge and a button that puts the default back. Used by the
	// tuning pages (through TuningParamRow) and Sample capture.
	import type { Snippet } from 'svelte';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';

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

	const revertLabel = $derived(
		`Put the default back${defaultLabel !== undefined ? `: ${defaultLabel}` : ''}`
	);
</script>

<div class="px-(--pad-panel) py-(--pad-row)">
	<div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-8">
		<div class="min-w-0">
			<div class="flex items-center gap-2">
				<label for={forId} class="text-sm font-medium text-ink">{label}</label>
				{#if changed}<Badge tone="warning">Changed</Badge>{/if}
			</div>
			{#if description}<p class="mt-0.5 max-w-prose text-sm text-ink-muted">{description}</p>{/if}
		</div>
		<div class="flex shrink-0 items-center gap-2">
			{#if changed && onRevert}
				<Button variant="ghost" size="sm" icon={RotateCcw} label={revertLabel} onclick={onRevert} />
			{/if}
			{@render children()}
		</div>
	</div>
</div>
