<script lang="ts">
	let {
		message = '',
		variant = 'success'
	}: {
		message: string;
		variant?: 'success' | 'error';
	} = $props();
</script>

{#if message}
	<div
		class="mb-4 border px-3 py-2 text-sm {variant === 'error'
			? 'border-red-500 bg-red-500/10 text-red-700 dark:text-red-400'
			: 'border-emerald-500 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300'}"
	>
		{message}
	</div>
{/if}
