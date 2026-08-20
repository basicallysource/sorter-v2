<script lang="ts">
	import type { Snippet } from 'svelte';
	import { AlertTriangle, CheckCircle2, XCircle, Info } from 'lucide-svelte';

	// Generic emphasized callout / alert box. Reuse for any status: info, success,
	// warning, danger. Optional bold title (larger than the body) + body content.
	type Variant = 'info' | 'success' | 'warning' | 'danger';
	let {
		variant = 'warning',
		title,
		children
	}: { variant?: Variant; title?: string; children: Snippet } = $props();

	const styles: Record<Variant, string> = {
		info: 'border-info/40 bg-info/[0.06] text-info',
		success: 'border-success/40 bg-success/[0.06] text-success-dark',
		warning: 'border-warning/50 bg-warning/[0.08] text-warning-dark',
		danger: 'border-danger/40 bg-danger/[0.06] text-danger-dark'
	};
	const icons = { info: Info, success: CheckCircle2, warning: AlertTriangle, danger: XCircle };
	const Icon = $derived(icons[variant]);
</script>

<div class="flex gap-2.5 border p-3 {styles[variant]}">
	<Icon size={18} class="mt-0.5 shrink-0" />
	<div class="min-w-0">
		{#if title}<div class="text-base font-semibold leading-tight">{title}</div>{/if}
		<div class="text-sm {title ? 'mt-1' : ''}">{@render children()}</div>
	</div>
</div>
