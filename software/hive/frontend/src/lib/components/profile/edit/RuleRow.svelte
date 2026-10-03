<!--
	One rule as a compact row: its place in the order, its bin's picture, its name
	and how many parts it takes, and a mark when something is wrong with it. The
	whole row chooses the rule; its menu (move, turn off, duplicate, delete) works
	on its own. The row can be dragged to another place, and the menu's move
	items do the same from a keyboard.
-->
<script module lang="ts">
	// What to say beside a rule that has something wrong with it.
	export type RowMark = { tone: 'warning' | 'danger'; text: string };
</script>

<script lang="ts">
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import Copy from '@lucide/svelte/icons/copy';
	import Ellipsis from '@lucide/svelte/icons/ellipsis';
	import GripVertical from '@lucide/svelte/icons/grip-vertical';
	import OctagonAlert from '@lucide/svelte/icons/octagon-alert';
	import ToggleLeft from '@lucide/svelte/icons/toggle-left';
	import ToggleRight from '@lucide/svelte/icons/toggle-right';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import type { ProfileBin } from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import Menu from '$lib/components/Menu.svelte';
	import PartImage from '$lib/components/PartImage.svelte';
	import { allConditions, isEmptyValue, isKitRule, plural, type Rule } from './rules';

	let {
		rule,
		bin,
		number,
		selected,
		mark = null,
		first,
		last,
		dropping = null,
		onselect,
		onmove,
		ontoggle,
		onduplicate,
		ondelete,
		ondragstart,
		ondragend,
		ondragover,
		ondrop
	}: {
		rule: Rule;
		// What the live preview made of it, for the picture and the count.
		bin: ProfileBin | undefined;
		number: number;
		selected: boolean;
		mark?: RowMark | null;
		first: boolean;
		last: boolean;
		// A drop here would land on this row's top or (for the last row) bottom edge.
		dropping?: 'before' | 'after' | null;
		onselect: () => void;
		onmove: (delta: -1 | 1) => void;
		ontoggle: () => void;
		onduplicate: () => void;
		ondelete: () => void;
		ondragstart: (event: DragEvent) => void;
		ondragend: () => void;
		ondragover: (event: DragEvent) => void;
		ondrop: (event: DragEvent) => void;
	} = $props();

	const meta = $derived.by(() => {
		if (rule.disabled) return 'Off';
		if (isKitRule(rule)) {
			const lines = bin?.kit?.line_count ?? bin?.part_count;
			return lines == null ? 'Kit' : `Kit, ${plural(lines, 'line')}`;
		}
		if (!bin || bin.part_count == null) return '';
		if (bin.any_part && bin.color_count) return `Any part in ${plural(bin.color_count, 'color')}`;
		if (bin.part_count === 0) return allConditions(rule).some((c) => c.field && !isEmptyValue(c.value)) ? 'Takes no parts' : 'Takes nothing yet';
		const parts = plural(bin.part_count, 'part');
		return bin.color_count ? `${parts}, ${plural(bin.color_count, 'color')}` : parts;
	});

	const picture = $derived(bin?.image_url ?? rule.image_url ?? null);
</script>

<li
	data-rule-id={rule.id}
	draggable="true"
	{ondragstart}
	{ondragend}
	{ondragover}
	{ondrop}
	class="group relative isolate {selected ? 'bg-primary-soft' : ''}"
>
	{#if dropping}
		<span
			aria-hidden="true"
			class="pointer-events-none absolute inset-x-0 z-10 h-0.5 bg-primary {dropping === 'before'
				? 'top-0'
				: 'bottom-0'}"
		></span>
	{/if}
	<button
		type="button"
		aria-label={rule.name}
		aria-current={selected ? 'true' : undefined}
		onclick={onselect}
		class="absolute inset-0 transition-colors hover:bg-hover active:bg-pressed"
	></button>
	<div class="pointer-events-none relative flex items-center gap-2 py-2 pr-2 pl-2 [&_button]:pointer-events-auto">
		<GripVertical size={16} class="shrink-0 cursor-grab text-ink-faint" aria-hidden="true" />
		<span class="num w-5 shrink-0 text-right text-sm text-ink-muted">{number}</span>
		<PartImage src={picture} class="size-10 shrink-0 {rule.disabled ? 'opacity-45' : ''}" />
		<div class="min-w-0 flex-1">
			<div class="truncate text-sm font-medium {rule.disabled ? 'text-ink-muted' : 'text-ink'}" title={rule.name}>
				{rule.name}
			</div>
			{#if meta}
				<div class="truncate text-sm text-ink-muted">{meta}</div>
			{/if}
		</div>
		{#if mark}
			<span title={mark.text} class="shrink-0">
				{#if mark.tone === 'danger'}
					<OctagonAlert size={16} class="text-danger-ink" aria-label={mark.text} />
				{:else}
					<TriangleAlert size={16} class="text-warning-ink" aria-label={mark.text} />
				{/if}
			</span>
		{/if}
		<Menu
			label="More about {rule.name}"
			width="13rem"
			items={[
				{ label: 'Move up', icon: ArrowUp, disabled: first, onselect: () => onmove(-1) },
				{ label: 'Move down', icon: ArrowDown, disabled: last, onselect: () => onmove(1) },
				'separator',
				{ label: rule.disabled ? 'Turn on' : 'Turn off', icon: rule.disabled ? ToggleRight : ToggleLeft, onselect: ontoggle },
				{ label: 'Duplicate', icon: Copy, onselect: onduplicate },
				'separator',
				{ label: 'Delete', icon: Trash2, danger: true, onselect: ondelete }
			]}
		>
			{#snippet trigger(props)}
				<Button {...props} variant="ghost" size="sm" icon={Ellipsis} label="More about {rule.name}" />
			{/snippet}
		</Menu>
	</div>
</li>
