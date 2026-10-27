<!--
	docs/components.md#color-review. One thing that can be wrong with the photos
	of a piece, as an icon that is its own switch: a click flags it, another
	takes the flag off, and the icon changes color (the warning tint, with its
	ink) while it is flagged, so a row of them reads at a glance and a piece is
	reviewed without opening anything. Pointing at it names it, after a short
	pause, in a tooltip (`label`, which is also its accessible name).

	It is 30px square, like any control in a dense row, and its glyph 20px
	(`IssueIcon`). The app saves the answer and passes `on` back; `busy` holds
	it while that is on its way.

	<IssueToggle glyph="blurry" label="Blurry" {on} onchange={() => toggle('blurry')} />
-->
<script lang="ts">
	import IssueIcon, { type IssueGlyph } from './IssueIcon.svelte';
	import Tooltip from './Tooltip.svelte';

	let {
		glyph,
		label,
		on = false,
		busy = false,
		onchange
	}: {
		glyph: IssueGlyph;
		// What it is, for the tooltip and for a screen reader.
		label: string;
		// Whether the issue is flagged.
		on?: boolean;
		busy?: boolean;
		onchange: () => void;
	} = $props();
</script>

<Tooltip text={label}>
	{#snippet children(tip)}
		<button
			{...tip}
			type="button"
			aria-label={label}
			aria-pressed={on}
			disabled={busy}
			onclick={onchange}
			class="inline-flex size-(--size-control-sm) shrink-0 items-center justify-center rounded-button transition-colors disabled:pointer-events-none disabled:opacity-45
				{on
				? 'bg-warning-soft text-warning-ink'
				: 'text-ink-muted hover:bg-hover hover:text-ink active:bg-pressed'}"
		>
			<IssueIcon {glyph} />
		</button>
	{/snippet}
</Tooltip>
