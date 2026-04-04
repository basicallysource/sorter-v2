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
			? 'border-[#D01012] bg-[#D01012]/10 text-[#D01012] dark:text-red-400'
			: 'border-[#00852B] bg-[#00852B]/10 text-[#00852B] dark:text-emerald-300'}"
	>
		{message}
	</div>
{/if}
