<script lang="ts">
	// General-purpose loading indicator: three little gray boxes that grow and
	// shrink in sequence. Sharp corners + neutral gray, per the design rules.
	let {
		size = 8,
		gap = 5,
		label = ''
	}: { size?: number; gap?: number; label?: string } = $props();
</script>

<div
	class="loading-boxes inline-flex items-center"
	style="--box: {size}px; --gap: {gap}px;"
	role="status"
	aria-label={label || 'Loading'}
>
	<span class="box"></span><span class="box"></span><span class="box"></span>
	{#if label}<span class="ml-2 text-sm text-text-muted">{label}</span>{/if}
</div>

<style>
	.loading-boxes {
		gap: var(--gap);
	}
	.loading-boxes .box {
		width: var(--box);
		height: var(--box);
		display: inline-block;
		background: #c9c6bf;
		animation: box-pulse 1s ease-in-out infinite;
	}
	.loading-boxes .box:nth-child(2) {
		animation-delay: 0.15s;
	}
	.loading-boxes .box:nth-child(3) {
		animation-delay: 0.3s;
	}
	@keyframes box-pulse {
		0%,
		100% {
			transform: scale(0.45);
			opacity: 0.35;
		}
		40% {
			transform: scale(1);
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.loading-boxes .box {
			animation: none;
			opacity: 0.6;
		}
	}
</style>
