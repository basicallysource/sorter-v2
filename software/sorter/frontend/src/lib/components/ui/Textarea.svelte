<!--
	docs/components.md#forms. Several lines of text: a note, a description.
	The same edge and focus as Input.
-->
<script lang="ts">
	let {
		value = $bindable(''),
		id,
		rows = 4,
		placeholder,
		invalid = false,
		disabled = false,
		class: className = '',
		oninput
	}: {
		value?: string;
		id?: string;
		rows?: number;
		placeholder?: string;
		invalid?: boolean;
		disabled?: boolean;
		class?: string;
		oninput?: (event: Event) => void;
	} = $props();
</script>

<textarea
	{id}
	{rows}
	{placeholder}
	{disabled}
	bind:value
	{oninput}
	aria-invalid={invalid || undefined}
	class="block w-full resize-y rounded-control border bg-field px-(--pad-control) py-2 text-sm text-ink transition-colors outline-none placeholder:text-ink-faint focus:border-primary focus:outline-2 focus:-outline-offset-1 focus:outline-primary disabled:pointer-events-none disabled:opacity-45
		{invalid
		? 'border-danger outline-2 -outline-offset-1 outline-danger'
		: 'border-line-strong hover:border-ink-faint'} {className}"
></textarea>
