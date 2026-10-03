<!--
	A list of plain values (several numbers, several words) typed into one
	field: each is added with Enter or a comma and shows as a chip with a
	button to remove it. Backspace in the empty field takes the last one back.
-->
<script lang="ts">
	import ValueBox from './ValueBox.svelte';
	import ValueChip from './ValueChip.svelte';

	let {
		values,
		type = 'text',
		placeholder = 'Type a value and press Enter',
		label,
		invalid = false,
		onchange
	}: {
		values: Array<string | number>;
		type?: 'text' | 'number';
		placeholder?: string;
		// The field's accessible name.
		label: string;
		invalid?: boolean;
		onchange: (values: Array<string | number>) => void;
	} = $props();

	let draft = $state('');

	function parse(raw: string): string | number | null {
		const text = raw.trim();
		if (!text) return null;
		if (type === 'text') return text;
		const number = Number(text.replace(/^\$/, ''));
		return Number.isFinite(number) ? number : null;
	}

	// Add what is typed; text that is not a value stays in the field for a fix.
	function commit(): boolean {
		const parts = draft.split(',');
		const added: Array<string | number> = [];
		for (const part of parts) {
			const value = parse(part);
			if (value !== null && !values.includes(value) && !added.includes(value)) added.push(value);
		}
		const allRead = parts.every((part) => !part.trim() || parse(part) !== null);
		if (added.length > 0) onchange([...values, ...added]);
		if (allRead) draft = '';
		return added.length > 0;
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' || event.key === ',') {
			event.preventDefault();
			commit();
		} else if (event.key === 'Backspace' && draft === '' && values.length > 0) {
			onchange(values.slice(0, -1));
		}
	}
</script>

<ValueBox {invalid} class="flex flex-wrap items-center gap-1 p-1 focus-within:border-primary focus-within:outline-2 focus-within:-outline-offset-1 focus-within:outline-primary">
	{#each values as item (item)}
		<ValueChip label={String(item)} onremove={() => onchange(values.filter((v) => v !== item))} />
	{/each}
	<input
		type="text"
		data-first-value
		inputmode={type === 'number' ? 'decimal' : 'text'}
		aria-label={label}
		placeholder={values.length === 0 ? placeholder : ''}
		autocomplete="off"
		bind:value={draft}
		{onkeydown}
		onblur={commit}
		class="h-7 min-w-28 flex-1 bg-transparent px-2 text-sm text-ink outline-none placeholder:text-ink-faint"
	/>
</ValueBox>
