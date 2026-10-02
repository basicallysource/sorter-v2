<!--
	docs/components.md#profiles. A rule's conditions as phrases anyone can
	read, every one built the same way: the field, the operator in words, then
	each value as a chip. A color is its swatch and name, a part its small
	picture, name and ID, a category its name, a number its unit; nothing is
	shown as a field name, an ID list or a UUID. Conditions joined by "all of"
	or "any of" say so once above them, and a group inside a rule is indented
	under its own "all of" or "any of". A negated group says "none of" or "not
	all of", even when it holds one condition.

	`limit` is how many chips one condition shows before "+N more", which opens
	the rest in place. A condition that cannot be evaluated yet is in the
	warning tone.

	<ConditionList conditions={bin.conditions} limit={6} />
-->
<script module lang="ts">
	// What Hive sends for a bin (the BinConditions types in Hive's api.ts).
	export interface BinConditionValue {
		value: unknown;
		label: string;
		// A color's RGB: six hex digits, no #.
		rgb?: string | null;
		// A part's picture and IDs.
		img_url?: string | null;
		part_num?: string;
		bricklink_id?: string;
	}

	export interface BinCondition {
		id?: string;
		field: string;
		field_label: string;
		op: string;
		op_label: string;
		values: BinConditionValue[];
		invalid?: boolean;
	}

	export interface BinConditions {
		mode: 'all' | 'any' | string;
		// "None of" (with any) or "not all of" (with all).
		negate?: boolean;
		items: BinCondition[];
		groups: Array<BinConditions & { id?: string; name?: string }>;
	}
</script>

<script lang="ts">
	import ColorChip from './ColorChip.svelte';
	import PartImage from './PartImage.svelte';

	let { conditions, limit = 6 }: { conditions: BinConditions; limit?: number } = $props();

	// The conditions whose chips are all showing, by their place in the tree.
	let opened = $state<Record<string, boolean>>({});

	// A value is a color when Hive gave it an RGB (even an empty one), a part
	// when it gave it a picture or IDs.
	function isColor(value: BinConditionValue) {
		return value.rgb !== undefined;
	}
	function isPart(value: BinConditionValue) {
		return value.img_url !== undefined || value.part_num !== undefined;
	}
	// A part's ID, unless its name already is the ID.
	function partId(value: BinConditionValue) {
		const id = value.bricklink_id ?? value.part_num;
		return id && id !== value.label ? id : null;
	}

	function visible(condition: BinCondition, path: string) {
		const values = condition.values;
		// "+1 more" takes the room of the chip it hides.
		if (opened[path] || values.length <= limit + 1) return values;
		return values.slice(0, limit);
	}

	function size(group: BinConditions) {
		return group.items.length + group.groups.length;
	}

	// Said above a group: always when it is negated, else when it joins several.
	function heading(group: BinConditions): string | null {
		if (group.negate) return group.mode === 'any' || size(group) === 1 ? 'None of' : 'Not all of';
		if (size(group) < 2) return null;
		return group.mode === 'any' ? 'Any of' : 'All of';
	}
</script>

{#snippet chip(value: BinConditionValue, condition: BinCondition)}
	<span
		class="inline-flex min-h-6 max-w-full min-w-0 items-center gap-1.5 rounded-badge px-2 py-0.5 text-sm {condition.invalid
			? 'bg-warning-soft text-warning-ink'
			: 'bg-hover text-ink'}"
	>
		{#if isColor(value)}
			<ColorChip name={value.label} rgb={value.rgb} />
		{:else if isPart(value)}
			<PartImage src={value.img_url} class="size-5 shrink-0" />
			<span class="truncate" title={value.label}>{value.label}</span>
			{#if partId(value)}<span class="num shrink-0 text-ink-muted">{partId(value)}</span>{/if}
		{:else}
			<span
				class="truncate {condition.op === 'regex' ? 'font-mono' : ''}"
				title={value.label || undefined}>{value.label || 'No value yet'}</span
			>
		{/if}
	</span>
{/snippet}

{#snippet phrase(condition: BinCondition, path: string)}
	{@const values = visible(condition, path)}
	<div class="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm">
		<span class="font-medium {condition.invalid ? 'text-warning-ink' : 'text-ink'}"
			>{condition.field_label}</span
		>
		<span class="text-ink-muted">{condition.op_label}</span>
		{#each values as value, i (i)}{@render chip(value, condition)}{/each}
		{#if values.length < condition.values.length}
			<button
				type="button"
				onclick={() => (opened[path] = true)}
				class="inline-flex min-h-6 items-center rounded-badge px-2 text-sm font-medium text-primary-ink transition-colors hover:bg-hover active:bg-pressed"
			>
				+{condition.values.length - values.length} more
			</button>
		{:else if opened[path] && condition.values.length > limit + 1}
			<button
				type="button"
				onclick={() => (opened[path] = false)}
				class="inline-flex min-h-6 items-center rounded-badge px-2 text-sm font-medium text-primary-ink transition-colors hover:bg-hover active:bg-pressed"
			>
				Show fewer
			</button>
		{/if}
	</div>
{/snippet}

{#snippet members(group: BinConditions, path: string)}
	{@const words = heading(group)}
	{#if words}
		<div class="mb-1.5 text-sm font-medium text-ink-muted">{words}</div>
	{/if}
	<ul class="flex flex-col gap-2">
		{#each group.items as item, i (i)}
			<li>{@render phrase(item, `${path}.${i}`)}</li>
		{/each}
		{#each group.groups as child, i (i)}
			<li class={heading(child) ? 'pl-4' : ''}>{@render members(child, `${path}.g${i}`)}</li>
		{/each}
	</ul>
{/snippet}

{#if size(conditions) === 0}
	<p class="text-sm text-ink-muted">No conditions yet.</p>
{:else}
	<div>{@render members(conditions, 'c')}</div>
{/if}
