<script lang="ts">
	let { size = 16, class: className = '' }: { size?: number; class?: string } = $props();
</script>

<div class="spinner {className}" style={`--spinner-size:${size}px`} role="status" aria-label="Loading">
	<i></i><i></i><i></i><i></i>
</div>

<style>
	/* Canonical loading indicator, ported from the Sorter UI
	   (software/sorter/frontend/src/lib/components/Spinner.svelte): four squares,
	   one lit at a time, snapping clockwise every quarter cycle. Discrete (not
	   eased) and sharp-cornered. Inherits color via currentColor and scales via
	   the size prop. Deliberately keeps animating under prefers-reduced-motion —
	   a frozen loading indicator reads as a hung process. */
	.spinner {
		position: relative;
		display: inline-block;
		flex: none;
		width: var(--spinner-size);
		height: var(--spinner-size);
		vertical-align: middle;
	}
	.spinner i {
		position: absolute;
		width: 42%;
		height: 42%;
		background: currentColor;
		opacity: 0.2;
		animation: spinner-quarter 0.667s linear infinite;
	}
	.spinner i:nth-child(1) { top: 0; left: 0; animation-delay: 0s; }
	.spinner i:nth-child(2) { top: 0; right: 0; animation-delay: 0.1667s; }
	.spinner i:nth-child(3) { bottom: 0; right: 0; animation-delay: 0.3333s; }
	.spinner i:nth-child(4) { bottom: 0; left: 0; animation-delay: 0.5s; }
	@keyframes spinner-quarter {
		0%, 24% { opacity: 1; }
		25%, 100% { opacity: 0.2; }
	}
</style>
