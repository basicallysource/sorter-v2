<!--
	One condition of a rule, made of three choices and never typed as data: the
	field (named for what it is, grouped, from the server's own list), how it is
	compared (only what that field takes, in words), and the value, edited by
	what the field is: parts are searched and shown by picture, colors and
	categories are chosen from the catalog, numbers carry their unit. What is
	wrong with the condition is said under it, and its value draws the red edge.
-->
<script lang="ts">
	import { tick } from 'svelte';
	import X from '@lucide/svelte/icons/x';
	import Button from '$lib/components/Button.svelte';
	import Select from '$lib/components/Select.svelte';
	import { catalog, type PartRef } from './catalog.svelte';
	import { fieldOptions, isMulti, opOptions, valueKind, withField, withOp } from './fields';
	import type { Condition } from './rules';
	import ChoiceValue from './value/ChoiceValue.svelte';
	import NumberValue from './value/NumberValue.svelte';
	import PartValue from './value/PartValue.svelte';
	import TextValue from './value/TextValue.svelte';
	import YesNoValue from './value/YesNoValue.svelte';

	let {
		condition,
		problem = null,
		autofocus = false,
		onchange,
		onremove
	}: {
		condition: Condition;
		// What is wrong with it, to say under it.
		problem?: string | null;
		// A condition just added: the field's choice is ready to open.
		autofocus?: boolean;
		onchange: (condition: Condition) => void;
		onremove: () => void;
	} = $props();

	let row = $state<HTMLElement | undefined>();
	$effect(() => {
		if (autofocus) row?.querySelector('button')?.focus();
	});

	const field = $derived(catalog.fieldByKey(condition.field));
	const kind = $derived(valueKind(field));
	const multi = $derived(isMulti(condition.op));

	// A field the server no longer has is still shown, by its key, and flagged.
	const unknownField = $derived(condition.field !== '' && field === undefined);
	const fields = $derived([
		...fieldOptions(catalog.fields),
		...(unknownField ? [{ value: condition.field, label: condition.field, hint: 'Unknown' }] : [])
	]);
	const ops = $derived(opOptions(field, condition.op, catalog.opWords));

	// The value is what comes after the field, so its first control is ready.
	function setField(key: string) {
		const next = catalog.fieldByKey(key);
		if (!next) return;
		onchange(withField(condition, field, next));
		void tick().then(() => row?.querySelector<HTMLElement>('[data-first-value]')?.focus());
	}

	function setValue(value: unknown) {
		onchange({ ...condition, value });
	}
</script>

<li bind:this={row} class="flex flex-col gap-2 py-3">
	<div class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 sm:grid-cols-[minmax(0,1fr)_11rem_auto]">
		<Select
			class="order-1"
			label="Field"
			placeholder="Choose a field"
			value={condition.field}
			options={fields}
			invalid={unknownField}
			onchange={setField}
		/>
		{#if field}
			<Select
				class="order-3 col-span-2 sm:order-2 sm:col-span-1"
				label="Comparison"
				value={condition.op}
				options={ops}
				onchange={(op) => onchange(withOp(condition, op))}
			/>
		{/if}
		<Button
			class="order-2 sm:order-3"
			variant="ghost"
			icon={X}
			label="Remove this condition"
			onclick={onremove}
		/>
	</div>

	{#if field}
		{#if kind === 'part'}
			<PartValue
				ref={field.ref as PartRef}
				{multi}
				value={condition.value}
				invalid={problem !== null}
				onchange={setValue}
			/>
		{:else if kind === 'color'}
			<ChoiceValue kind="color" {multi} value={condition.value} invalid={problem !== null} onchange={setValue} />
		{:else if kind === 'category'}
			<ChoiceValue
				kind={field.ref === 'bl_category' ? 'bl_category' : 'rb_category'}
				{multi}
				value={condition.value}
				invalid={problem !== null}
				onchange={setValue}
			/>
		{:else if kind === 'number'}
			<NumberValue
				label={field.label}
				unit={field.unit}
				integer={field.type === 'int'}
				{multi}
				value={condition.value}
				invalid={problem !== null}
				onchange={setValue}
			/>
		{:else if kind === 'yesno'}
			<YesNoValue label={field.label} value={condition.value} onchange={setValue} />
		{:else}
			<TextValue
				label={field.label}
				op={condition.op}
				{multi}
				value={condition.value}
				invalid={problem !== null}
				onchange={setValue}
			/>
		{/if}
	{/if}

	{#if problem}<p class="text-sm text-danger-ink">{problem}</p>{/if}
</li>
