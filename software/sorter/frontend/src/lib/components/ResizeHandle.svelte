<script lang="ts">
	let { orientation = 'vertical', onresize }: { orientation?: 'vertical' | 'horizontal'; onresize: (delta: number) => void } = $props();

	let dragging = $state(false);
	let start_pos = 0;

	function onPointerDown(e: PointerEvent) {
		dragging = true;
		start_pos = orientation === 'vertical' ? e.clientX : e.clientY;
		(e.target as HTMLElement).setPointerCapture(e.pointerId);
	}

	function onPointerMove(e: PointerEvent) {
		if (!dragging) return;
		const current = orientation === 'vertical' ? e.clientX : e.clientY;
		const delta = current - start_pos;
		if (delta !== 0) {
			onresize(delta);
			start_pos = current;
		}
	}

	function onPointerUp() {
		dragging = false;
	}
</script>

{#if orientation === 'vertical'}
	<div
		class="relative z-10 -mx-2 flex w-4 flex-shrink-0 cursor-col-resize items-center justify-center select-none"
		onpointerdown={onPointerDown}
		onpointermove={onPointerMove}
		onpointerup={onPointerUp}
		onpointercancel={onPointerUp}
		role="separator"
		aria-orientation="vertical"
	>
		<div class="flex flex-col items-center gap-[3px] opacity-40">
			<div class="h-1 w-1 rounded-full bg-text-muted"></div>
			<div class="h-1 w-1 rounded-full bg-text-muted"></div>
			<div class="h-1 w-1 rounded-full bg-text-muted"></div>
		</div>
	</div>
{:else}
	<div
		class="relative z-10 -my-2 flex h-4 flex-shrink-0 cursor-row-resize items-center justify-center select-none"
		onpointerdown={onPointerDown}
		onpointermove={onPointerMove}
		onpointerup={onPointerUp}
		onpointercancel={onPointerUp}
		role="separator"
		aria-orientation="horizontal"
	>
		<div class="flex items-center gap-[3px] opacity-40">
			<div class="h-1 w-1 rounded-full bg-text-muted"></div>
			<div class="h-1 w-1 rounded-full bg-text-muted"></div>
			<div class="h-1 w-1 rounded-full bg-text-muted"></div>
		</div>
	</div>
{/if}
