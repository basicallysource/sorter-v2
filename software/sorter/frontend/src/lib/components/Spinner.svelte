<script lang="ts">
	let { size = 16, class: className = '' }: { size?: number; class?: string } = $props();
</script>

<div
	class="sorter-spinner {className}"
	style={`--spinner-size:${size}px`}
	role="status"
	aria-label="Loading"
>
	<i></i><i></i><i></i><i></i>
</div>

<style>
	/* Canonical loading indicator: four squares, one lit at a time, snapping
	   clockwise every quarter cycle. Discrete (not eased) and sharp-cornered to
	   match the industrial style. Inherits color via currentColor and scales via
	   the size prop. Deliberately keeps animating under prefers-reduced-motion —
	   a frozen loading indicator reads as a hung process. */
	.sorter-spinner {
		position: relative;
		display: inline-block;
		flex: none;
		width: var(--spinner-size);
		height: var(--spinner-size);
		vertical-align: middle;
	}
	.sorter-spinner i {
		position: absolute;
		width: 42%;
		height: 42%;
		background: currentColor;
		opacity: 0.2;
		animation: sorter-spinner-quarter 0.667s linear infinite;
	}
	.sorter-spinner i:nth-child(1) { top: 0; left: 0; animation-delay: 0s; }
	.sorter-spinner i:nth-child(2) { top: 0; right: 0; animation-delay: 0.1667s; }
	.sorter-spinner i:nth-child(3) { bottom: 0; right: 0; animation-delay: 0.3333s; }
	.sorter-spinner i:nth-child(4) { bottom: 0; left: 0; animation-delay: 0.5s; }
	@keyframes sorter-spinner-quarter {
		0%, 24% { opacity: 1; }
		25%, 100% { opacity: 0.2; }
	}
</style>
