<!--
	The middle of the editor for a rule made of conditions: its name, its
	picture, and its conditions as choices (see ConditionRow). A rule still
	named "Rule 3" takes its name from the first part, color or category chosen,
	until someone types a name of their own.
-->
<script lang="ts">
	import { api, type ProfileDocument } from '$lib/api';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { catalog, type PartRef } from './catalog.svelte';
	import ConditionGroup from './ConditionGroup.svelte';
	import { toList, valueKind } from './fields';
	import RulePicture, { type Candidate } from './RulePicture.svelte';
	import { allConditions, firstCondition, hasDefaultName, type Condition, type Rule } from './rules';

	let {
		rule,
		imageUrl,
		warnings,
		ruleProblems,
		problemFor,
		draft,
		onchange,
		ontoggle
	}: {
		rule: Rule;
		// The picture the bin shows now (the rule's own, or its best known part).
		imageUrl: string | null;
		warnings: string[];
		// What is wrong with the rule as a whole, not with one condition.
		ruleProblems: string[];
		problemFor: (condition: Condition) => string | null;
		// The draft, to find the parts a picture can be chosen from.
		draft: ProfileDocument;
		onchange: (rule: Rule) => void;
		ontoggle: () => void;
	} = $props();

	const uid = $props.id();

	let nameTyped = $state(false);
	let autoName = $state<string | null>(null);

	// What the first condition is about, in a few words: the parts, colors or
	// categories it names. Nothing for "is not": that is what the rule leaves out.
	function nameFrom(next: Rule): string | null {
		const condition = firstCondition(next);
		if (!condition || condition.op === 'neq' || condition.op === 'not_in') return null;
		const field = catalog.fieldByKey(condition.field);
		const kind = valueKind(field);
		const values = toList(condition.value);
		const names: string[] = [];
		for (const value of values) {
			let name: string | undefined;
			if (kind === 'part') name = catalog.part(field?.ref as PartRef, value)?.name;
			else if (kind === 'color') name = catalog.colorById.get(Number(value))?.name;
			else if (kind === 'category') {
				const lookup = field?.ref === 'bl_category' ? catalog.blCategoryById : catalog.rbCategoryById;
				name = lookup.get(Number(value))?.name;
			}
			if (name) names.push(name.startsWith('[') ? name.replace(/^\[|\]$/g, '') : name);
		}
		if (names.length === 0) return null;
		const more = names.length > 2 ? ` and ${names.length - 2} more` : '';
		return `${names.slice(0, 2).join(', ')}${more}`;
	}

	function change(next: Rule) {
		if (!nameTyped && (hasDefaultName(rule) || rule.name === autoName)) {
			const suggested = nameFrom(next);
			if (suggested && suggested !== next.name) {
				autoName = suggested;
				next = { ...next, name: suggested };
			}
		}
		onchange(next);
	}

	async function loadCandidates(query: string): Promise<Candidate[]> {
		const res = await api.previewSortingRule(draft, { rule_id: rule.id, q: query, limit: 24 });
		return res.items.map((part) => ({
			key: part.part_num,
			name: part.name,
			imgUrl: part.img_url,
			bricklinkId: part.bricklink_id,
			partNum: part.part_num
		}));
	}

	$effect(() => {
		void catalog.ensureFields();
	});

	// A rule on what the machine observes about a piece (how sure recognition
	// was, whether it named a part, its price in its color) is decided as each
	// piece is sorted, so the preview cannot count its parts for certain.
	const onThePiece = $derived(allConditions(rule).some((condition) => catalog.fieldByKey(condition.field)?.piece));
</script>

<div class="flex flex-col gap-5">
	{#if rule.disabled}
		<Alert tone="info" title="This rule is off">
			Pieces it would take go on to the rules below it.
			{#snippet actions()}
				<Button size="sm" onclick={ontoggle}>Turn it on</Button>
			{/snippet}
		</Alert>
	{/if}

	<div class="flex flex-col gap-4">
		<Field label="Name" for="{uid}-name">
			<Input
				id="{uid}-name"
				value={rule.name}
				autocomplete="off"
				oninput={(e) => {
					nameTyped = true;
					onchange({ ...rule, name: (e.currentTarget as HTMLInputElement).value });
				}}
			/>
		</Field>
		<RulePicture
			{imageUrl}
			own={Boolean(rule.image_url)}
			{loadCandidates}
			onchange={(url) => onchange({ ...rule, image_url: url })}
		/>
	</div>

	{#if ruleProblems.length > 0}
		<Alert tone="danger">
			{#each ruleProblems as message, i (i)}<p>{message}</p>{/each}
		</Alert>
	{/if}
	{#if warnings.length > 0}
		<Alert tone="warning">
			{#each warnings as message, i (i)}<p>{message}</p>{/each}
		</Alert>
	{/if}
	{#if onThePiece}
		<Alert tone="info" title="Decided on the machine">
			This rule tests the piece itself, so the machine decides it as each piece is sorted, and the parts shown are
			the ones it can take. It needs the sorter's current software.
		</Alert>
	{/if}

	<div class="border-t border-line pt-5">
		<h3 class="mb-3 text-base font-semibold text-ink">Conditions</h3>
		{#if catalog.fields.length === 0}
			<p class="flex items-center gap-2 text-sm text-ink-muted">
				<Spinner size={14} />{catalog.error ?? 'Loading the fields'}
			</p>
		{:else}
			{#if rule.conditions.length === 0 && rule.children.length === 0}
				<p class="mb-3 rounded-control bg-well px-3 py-3 text-sm text-ink-muted">
					No conditions yet. A rule with no conditions takes nothing.
				</p>
			{/if}
			<ConditionGroup group={rule} {problemFor} onchange={change} />
		{/if}
	</div>
</div>
