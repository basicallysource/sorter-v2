<!--
	docs/components.md#forms. On or off, applied the moment it changes. A
	square track and a square thumb; the thumb is the one part that moves.
	It needs a name: pass `label`, or put it in a SettingRow and pass the
	row's `id` as `labelledby`.
-->
<script lang="ts">
	let {
		checked = $bindable(false),
		label,
		labelledby,
		disabled = false,
		onchange
	}: {
		checked?: boolean;
		label?: string;
		labelledby?: string;
		disabled?: boolean;
		onchange?: (checked: boolean) => void;
	} = $props();

	function toggle() {
		checked = !checked;
		onchange?.(checked);
	}
</script>

<button
	type="button"
	role="switch"
	aria-checked={checked}
	aria-label={label}
	aria-labelledby={labelledby}
	{disabled}
	onclick={toggle}
	class="relative inline-flex h-5 w-9 shrink-0 items-center p-0.5 transition-colors disabled:pointer-events-none disabled:opacity-45
		{checked ? 'bg-primary hover:bg-primary-hover' : 'bg-line-strong hover:bg-ink-faint'}"
>
	<span
		class="size-4 bg-white shadow-(--shadow-thumb) transition-transform duration-150 {checked
			? 'translate-x-4'
			: 'translate-x-0'}"
	></span>
</button>
