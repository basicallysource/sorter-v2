<script lang="ts">
	type InputType = 'text' | 'number' | 'password' | 'email' | 'search';

	let {
		type = 'text',
		value = $bindable(''),
		placeholder = '',
		disabled = false,
		readonly = false,
		class: className = '',
		onchange,
		oninput
	}: {
		type?: InputType;
		value?: string | number;
		placeholder?: string;
		disabled?: boolean;
		readonly?: boolean;
		class?: string;
		onchange?: (event: Event) => void;
		oninput?: (event: Event) => void;
	} = $props();
</script>

<input
	{type}
	bind:value
	{placeholder}
	{disabled}
	{readonly}
	{onchange}
	{oninput}
	class="setup-control w-full px-3 py-2 text-sm text-text disabled:cursor-not-allowed disabled:opacity-60 {className}"
/>
