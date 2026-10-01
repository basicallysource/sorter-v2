<!--
	docs/components.md#forms. Several lines of text: a note, a description.
	The same edge and focus as Input. Every other attribute (id, name,
	required, maxlength, onkeydown) goes on the <textarea>.
-->
<script lang="ts">
	import type { HTMLTextareaAttributes } from 'svelte/elements';

	let {
		value = $bindable(''),
		rows = 4,
		invalid = false,
		class: className = '',
		...rest
	}: {
		value?: string;
		rows?: number;
		invalid?: boolean;
		class?: string;
	} & Omit<HTMLTextareaAttributes, 'value' | 'rows' | 'class'> = $props();
</script>

<textarea
	{...rest}
	{rows}
	bind:value
	aria-invalid={invalid || undefined}
	class="block w-full resize-y rounded-control border bg-field px-(--pad-control) py-2 text-sm text-ink transition-colors outline-none placeholder:text-ink-faint focus:border-primary focus:outline-2 focus:-outline-offset-1 focus:outline-primary disabled:pointer-events-none disabled:opacity-45
		{invalid
		? 'border-danger outline-2 -outline-offset-1 outline-danger'
		: 'border-line-strong hover:border-ink-faint'} {className}"
></textarea>
