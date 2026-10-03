<!--
	A set of conditions joined by "all of" or "any of", and the groups inside
	it, which are the same thing again with their own "all of" or "any of". A
	rule is one of these at its top; "red or blue" inside "all of" is a group.
	Every edit hands back the whole group, changed, for the parent to swap in.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Button from '$lib/components/Button.svelte';
	import Select from '$lib/components/Select.svelte';
	import ConditionRow from './ConditionRow.svelte';
	import Self from './ConditionGroup.svelte';
	import {
		newCondition,
		newGroup,
		removeChild,
		removeCondition,
		replaceChild,
		replaceCondition,
		type Condition,
		type Rule
	} from './rules';

	let {
		group,
		depth = 0,
		problemFor,
		onchange,
		onremove
	}: {
		group: Rule;
		// 0 for the rule itself, 1 for a group in it, and so on.
		depth?: number;
		// What to say under a condition that is wrong, or null.
		problemFor: (condition: Condition) => string | null;
		onchange: (group: Rule) => void;
		// A group can be taken out; the rule itself cannot.
		onremove?: () => void;
	} = $props();

	// Groups in groups in groups are a puzzle, not a rule.
	const MAX_DEPTH = 2;

	const modes = [
		{ value: 'all', label: 'all of' },
		{ value: 'any', label: 'any of' }
	];

	// The condition just added, whose field is ready to be chosen: a new rule's
	// first one is too.
	let fresh = $state<string | null>(
		untrack(() => (group.conditions.length === 1 && !group.conditions[0].field ? group.conditions[0].id : null))
	);

	function addCondition() {
		const condition = newCondition();
		fresh = condition.id;
		onchange({ ...group, conditions: [...group.conditions, condition] });
	}

	function addGroup() {
		onchange({ ...group, children: [...group.children, newGroup(group.match_mode)] });
	}
</script>

<div class={depth > 0 ? 'border-l border-line pl-4' : ''}>
	<div class="flex flex-wrap items-center gap-x-2 gap-y-1 pb-1">
		{#if depth === 0}
			<span class="text-sm text-ink">This rule takes a piece when it matches</span>
		{/if}
		<Select
			class="w-28"
			size="sm"
			label="How the conditions combine"
			value={group.match_mode}
			options={modes}
			onchange={(mode) => onchange({ ...group, match_mode: mode })}
		/>
		<span class="text-sm text-ink">these{depth === 0 ? ':' : ''}</span>
		{#if onremove}
			<Button
				class="ml-auto"
				variant="ghost"
				size="sm"
				icon={Trash2}
				label="Remove this group"
				onclick={onremove}
			/>
		{/if}
	</div>

	{#if group.conditions.length > 0}
		<ul class="divide-y divide-line">
			{#each group.conditions as condition (condition.id)}
				<ConditionRow
					{condition}
					problem={problemFor(condition)}
					autofocus={fresh === condition.id}
					onchange={(next) => onchange(replaceCondition(group, condition.id, next))}
					onremove={() => onchange(removeCondition(group, condition.id))}
				/>
			{/each}
		</ul>
	{/if}

	{#each group.children as child (child.id)}
		<div class="mt-2 {group.conditions.length > 0 ? 'border-t border-line pt-3' : ''}">
			<Self
				group={child}
				depth={depth + 1}
				{problemFor}
				onchange={(next) => onchange(replaceChild(group, child.id, next))}
				onremove={() => onchange(removeChild(group, child.id))}
			/>
		</div>
	{/each}

	<div class="flex flex-wrap items-center gap-2 pt-3">
		<Button variant="secondary" size="sm" icon={Plus} onclick={addCondition}>Add condition</Button>
		{#if depth < MAX_DEPTH}
			<Button variant="ghost" size="sm" icon={Plus} onclick={addGroup}>Add group</Button>
		{/if}
	</div>
</div>
