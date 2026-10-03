<!--
	A condition's value when it is words: one line of text ("contains" and
	"matches" say what to look for), or for "is one of" a list of words typed one
	by one.
-->
<script lang="ts">
	import Input from '$lib/components/Input.svelte';
	import { toList, valuePlaceholder } from '../fields';
	import TokenList from './TokenList.svelte';

	let {
		label,
		op,
		multi,
		value,
		invalid = false,
		onchange
	}: {
		label: string;
		op: string;
		multi: boolean;
		value: unknown;
		invalid?: boolean;
		onchange: (value: unknown) => void;
	} = $props();
</script>

{#if multi}
	<TokenList
		{label}
		{invalid}
		placeholder={valuePlaceholder('text', op)}
		values={toList(value).map(String)}
		{onchange}
	/>
{:else}
	<Input
		type="text"
		data-first-value
		aria-label={label}
		placeholder={valuePlaceholder('text', op)}
		value={typeof value === 'string' ? value : value == null ? '' : String(value)}
		{invalid}
		autocomplete="off"
		class={op === 'regex' ? 'font-mono' : ''}
		oninput={(e) => onchange((e.currentTarget as HTMLInputElement).value)}
	/>
{/if}
