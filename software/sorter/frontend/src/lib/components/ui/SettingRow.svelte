<!--
	docs/components.md#settings. One setting: its name and a sentence on the
	left, its control on the right; stacked on a narrow screen. Rows go in a
	`divide-y divide-line` list inside a flush Panel, so a line sits only
	between two rows, never above the first or below the last.

	`tags` holds a Badge or two that sit beside the name (where the setting
	acts, that it is active now).

	`below` holds what belongs to the setting but is wider than a control (a
	chart, a set of sub-settings): it renders under the row, in a well.

	`changed` marks a setting that is not at its default: the row takes the
	primary's tint (state is a fill), and one button beside its name puts the
	default back. It sits on the name's line at the name's height, so the row
	never jumps as a value changes. `defaultText` says what the default is, on
	that button ("Reset to 6 /min"). Pointing at the button (or focusing it)
	shows a tooltip saying what the default is: `defaultHelp` when the default
	needs a sentence ("Automatic: turn the channel forward until it clears."),
	"Default: 6 /min" otherwise.

	<SettingRow label="Burst rate" for="burst" changed={burst !== 6}
		defaultText="6 /min" onreset={() => (burst = 6)}>...</SettingRow>
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Tooltip from './Tooltip.svelte';

	let {
		label,
		help,
		for: forId,
		changed = false,
		defaultText,
		defaultHelp,
		onreset,
		tags,
		children,
		below
	}: {
		label: string;
		help?: string;
		for?: string;
		// Not at its default: needs `onreset` to put the default back.
		changed?: boolean;
		defaultText?: string;
		// The reset button's tooltip, when the default needs a sentence.
		defaultHelp?: string;
		onreset?: () => void;
		tags?: Snippet;
		children?: Snippet;
		below?: Snippet;
	} = $props();

	const resetTip = $derived(
		defaultHelp ?? (defaultText ? `Default: ${defaultText}` : 'Puts the default back')
	);
</script>

<div class="px-(--pad-panel) py-(--pad-row) transition-colors {changed ? 'bg-primary-soft' : ''}">
	<div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-8">
		<div class="min-w-0">
			<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
				{#if forId}
					<label for={forId} class="text-sm font-medium text-ink">{label}</label>
				{:else}
					<div class="text-sm font-medium text-ink">{label}</div>
				{/if}
				{#if tags}{@render tags()}{/if}
				{#if changed && onreset}
					<Tooltip text={resetTip}>
						{#snippet children(props)}
							<button
								{...props}
								type="button"
								onclick={onreset}
								class="-my-0.5 inline-flex items-center gap-1 rounded-item px-1.5 py-0.5 text-sm font-medium text-primary-ink transition-colors hover:bg-hover active:bg-pressed"
							>
								<RotateCcw size={14} class="shrink-0" />
								{defaultText ? `Reset to ${defaultText}` : 'Reset to default'}
							</button>
						{/snippet}
					</Tooltip>
				{/if}
			</div>
			{#if help}<p class="mt-0.5 max-w-prose text-sm text-ink-muted">{help}</p>{/if}
		</div>
		{#if children}<div class="flex shrink-0 items-center gap-2">{@render children()}</div>{/if}
	</div>
	{#if below}<div class="mt-3 overflow-hidden rounded-control bg-well">{@render below()}</div>{/if}
</div>
