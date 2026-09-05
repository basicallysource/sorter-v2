<script lang="ts">
	interface Props {
		found: number;
		needed: number;
		pct: number;
		compact?: boolean;
	}

	let { found, needed, pct, compact = false }: Props = $props();
	const complete = $derived(needed > 0 && found >= needed);
</script>

<div>
	<div class="flex items-baseline justify-between gap-2 {compact ? 'text-[11px]' : 'text-xs'}">
		<span class="text-text-muted">{found} / {needed} parts</span>
		<span class="font-medium {complete ? 'text-success' : 'text-text'}">{pct.toFixed(pct >= 100 || pct === 0 ? 0 : 1)}%</span>
	</div>
	<div class="mt-1 h-1.5 w-full bg-border">
		<div class="h-full {complete ? 'bg-success' : 'bg-primary'}" style="width: {Math.min(100, Math.max(0, pct))}%"></div>
	</div>
</div>
