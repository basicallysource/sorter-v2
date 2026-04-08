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
		class="mb-4 border px-3 py-2 text-xs leading-relaxed text-text {variant === 'error'
			? 'border-[#D01012]/40 bg-[#D01012]/[0.06] dark:border-rose-500/40 dark:bg-rose-500/[0.08]'
			: variant === 'warning'
				? 'border-[#F2A900]/50 bg-[#F2A900]/[0.07] dark:border-amber-500/40 dark:bg-amber-500/[0.08]'
				: 'border-[#00852B]/40 bg-[#00852B]/[0.06] dark:border-emerald-500/40 dark:bg-emerald-500/[0.08]'}"
	>
		{message}
	</div>
{/if}
