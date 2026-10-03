<!--
	A condition's value when it is a number: a field with its unit after the
	value ($, g, studs), or for "is one of" a list of numbers typed one by one.
	What is typed stays as typed until it is a number, so "1." on the way to
	"1.5" is not rewritten under the cursor.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import Input from '$lib/components/Input.svelte';
	import { toList } from '../fields';
	import TokenList from './TokenList.svelte';

	let {
		label,
		unit = null,
		integer = false,
		multi,
		value,
		invalid = false,
		onchange
	}: {
		// The field's name, for the control's accessible name.
		label: string;
		unit?: string | null;
		// Whole numbers only (years, counts): the arrows step by one.
		integer?: boolean;
		multi: boolean;
		value: unknown;
		invalid?: boolean;
		onchange: (value: unknown) => void;
	} = $props();

	function asNumber(raw: unknown): number | null {
		if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
		if (typeof raw === 'string' && raw.trim() !== '') {
			const n = Number(raw.replace(/^\$/, ''));
			return Number.isFinite(n) ? n : null;
		}
		return null;
	}

	const current = $derived(asNumber(value));
	let text = $state(untrack(() => (current === null ? '' : String(current))));

	// Follow the value when something else changed it (a new field, a reload),
	// but never overwrite what is being typed into a number it already means.
	$effect(() => {
		if (asNumber(text) !== current) text = current === null ? '' : String(current);
	});

	function onInput(event: Event) {
		text = (event.currentTarget as HTMLInputElement).value;
		onchange(asNumber(text) ?? '');
	}
</script>

{#if multi}
	<TokenList
		type="number"
		{label}
		{invalid}
		values={toList(value)
			.map(asNumber)
			.filter((n): n is number => n !== null)}
		onchange={onchange}
	/>
{:else}
	<Input
		type="number"
		data-first-value
		aria-label={label}
		step={integer ? 1 : 'any'}
		value={text}
		{invalid}
		unit={unit ?? undefined}
		oninput={onInput}
	/>
{/if}
