<script lang="ts">
	type InputType = 'text' | 'number' | 'password' | 'email' | 'search';

	let {
		id,
		type = 'text',
		step,
		value = $bindable(''),
		placeholder = '',
		disabled = false,
		readonly = false,
		class: className = '',
		onchange,
		oninput
	}: {
		id?: string;
		type?: InputType;
		step?: string | number;
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
	{id}
	{type}
	{step}
	bind:value
	{placeholder}
	{disabled}
	{readonly}
	{onchange}
	{oninput}
	class="setup-control w-full px-3 py-2 text-sm text-ink disabled:cursor-not-allowed disabled:opacity-60 {className}"
/>
