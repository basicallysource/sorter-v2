<script lang="ts">
	// Consolidates the switch markup that was copy-pasted across the bins page.
	// Keeps the established pill/rounded look those switches already shipped with
	// (predates the sharp-edges rule); changing the shape is now a one-file edit.
	let {
		checked,
		label,
		disabled = false,
		size = 'md',
		onToggle
	}: {
		checked: boolean;
		label: string;
		disabled?: boolean;
		size?: 'sm' | 'md';
		onToggle: () => void;
	} = $props();
</script>

<button
	type="button"
	role="switch"
	aria-checked={checked}
	aria-label={label}
	onclick={onToggle}
	{disabled}
	class="relative inline-flex items-center rounded-full transition-colors {size === 'md'
		? 'h-6 w-11'
		: 'h-5 w-9'} {checked ? 'bg-success' : 'bg-[#C9C6BF]'} disabled:cursor-not-allowed disabled:opacity-50"
>
	<span
		class="inline-block transform rounded-full bg-white transition-transform {size === 'md'
			? 'h-4 w-4'
			: 'h-3.5 w-3.5'} {checked ? (size === 'md' ? 'translate-x-6' : 'translate-x-5') : 'translate-x-1'}"
	></span>
</button>
