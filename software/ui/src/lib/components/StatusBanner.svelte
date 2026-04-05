<script lang="ts">
	let {
		message = '',
		variant = 'success'
	}: {
		message: string;
		variant?: 'success' | 'warning' | 'error';
	} = $props();
</script>

{#if message}
	<div
		class="mb-4 border px-4 py-3 text-sm {variant === 'error'
			? 'border-[#D01012]/30 bg-[#D01012]/8 text-[#D01012] dark:text-red-400'
			: variant === 'warning'
				? 'border-amber-500/30 bg-amber-500/8 text-amber-700 dark:text-amber-300'
				: 'border-[#00852B]/25 bg-[#00852B]/6 text-text dark:text-emerald-200'}"
	>
		{message}
	</div>
{/if}
