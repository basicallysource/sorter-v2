<!--
	docs/components.md#forms. On or off, applied the moment it changes. The
	track and the knob take the button corners, and the knob is the one part
	that moves. It sizes with the density.
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
	class="relative inline-flex h-(--switch-h) w-(--switch-w) shrink-0 items-center rounded-button p-0.5 transition-colors disabled:pointer-events-none disabled:opacity-45
		{checked ? 'bg-primary hover:bg-primary-hover' : 'bg-line-strong hover:bg-ink-faint'}"
>
	<span
		class="size-[calc(var(--switch-h)-4px)] rounded-button-inner bg-knob transition-transform duration-150 {checked
			? 'translate-x-[calc(var(--switch-w)-var(--switch-h))]'
			: 'translate-x-0'}"
	></span>
</button>
