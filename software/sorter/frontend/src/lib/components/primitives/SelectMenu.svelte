<script lang="ts">
	import type { Snippet } from 'svelte';
	import { tick } from 'svelte';
	import Input from './Input.svelte';

	// Click-open, viewport-aware select menu with an optional search box. The
	// panel is portaled to <body> and uses `position: fixed`, so it is NEVER
	// clipped by an ancestor's `overflow` (e.g. a scrolling Modal). It flips
	// above/below the trigger depending on room, clamps into the viewport, and
	// sizes its scroll area to the space available — so it can show a lot without
	// ever running off-screen. The trigger and the list rows are passed in as
	// snippets; this component only owns positioning, the search box, and
	// open/close behavior.
	let {
		open = $bindable(false),
		search = $bindable(''),
		searchable = true,
		searchPlaceholder = 'Search…',
		width = 288,
		maxPanelHeight = 384,
		minPanelHeight = 180,
		align = 'left',
		trigger,
		children
	}: {
		open?: boolean;
		search?: string;
		searchable?: boolean;
		searchPlaceholder?: string;
		width?: number;
		maxPanelHeight?: number;
		minPanelHeight?: number;
		align?: 'left' | 'right';
		trigger: Snippet;
		children: Snippet;
	} = $props();

	const GAP = 4; // distance from trigger to panel
	const MARGIN = 8; // keep this far from every viewport edge

	let triggerEl = $state<HTMLElement | null>(null);
	let panelEl = $state<HTMLElement | null>(null);
	let searchEl = $state<HTMLElement | null>(null);
	let ready = $state(false); // positioned yet? avoids a flash at (0,0)
	let placeBelow = $state(true);
	let top = $state(0);
	let bottom = $state(0);
	let left = $state(0);
	let panelWidth = $state(width);
	let maxHeight = $state(maxPanelHeight);

	function portal(node: HTMLElement) {
		document.body.appendChild(node);
		return {
			destroy() {
				node.remove();
			}
		};
	}

	async function reposition() {
		if (!open || !triggerEl) return;
		await tick();
		const t = triggerEl.getBoundingClientRect();
		const vw = window.innerWidth;
		const vh = window.innerHeight;

		panelWidth = Math.min(Math.max(width, t.width), vw - 2 * MARGIN);

		const spaceBelow = vh - t.bottom - GAP - MARGIN;
		const spaceAbove = t.top - GAP - MARGIN;
		// Prefer dropping down; only flip up when there isn't room below for a
		// usable panel and there's more room above.
		placeBelow = !(spaceBelow < minPanelHeight && spaceAbove > spaceBelow);
		const avail = placeBelow ? spaceBelow : spaceAbove;
		maxHeight = Math.max(0, Math.min(maxPanelHeight, avail));

		let placeLeft = align === 'right' ? t.right - panelWidth : t.left;
		left = Math.max(MARGIN, Math.min(placeLeft, vw - panelWidth - MARGIN));

		if (placeBelow) top = t.bottom + GAP;
		else bottom = vh - t.top + GAP;

		ready = true;
	}

	function toggle() {
		open = !open;
	}

	function onPointerDown(event: PointerEvent) {
		const target = event.target as Node;
		if (triggerEl?.contains(target) || panelEl?.contains(target)) return;
		open = false;
	}

	function onKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') open = false;
	}

	$effect(() => {
		if (!open) {
			ready = false;
			return;
		}
		reposition();
		// Focus the search box so the operator can type immediately.
		tick().then(() => searchEl?.querySelector('input')?.focus());
		const onMove = () => reposition();
		window.addEventListener('scroll', onMove, true);
		window.addEventListener('resize', onMove);
		window.addEventListener('pointerdown', onPointerDown, true);
		window.addEventListener('keydown', onKeydown);
		return () => {
			window.removeEventListener('scroll', onMove, true);
			window.removeEventListener('resize', onMove);
			window.removeEventListener('pointerdown', onPointerDown, true);
			window.removeEventListener('keydown', onKeydown);
		};
	});
</script>

<span bind:this={triggerEl} class="inline-flex" onclick={toggle} role="presentation">
	{@render trigger()}
</span>

{#if open}
	<div
		use:portal
		bind:this={panelEl}
		class="fixed z-[100] flex flex-col border border-border bg-white shadow-lg {ready
			? ''
			: 'pointer-events-none opacity-0'}"
		style="left: {left}px; width: {panelWidth}px; max-height: {maxHeight}px; {placeBelow
			? `top: ${top}px;`
			: `bottom: ${bottom}px;`}"
		role="listbox"
		tabindex="-1"
	>
		{#if searchable}
			<div bind:this={searchEl} class="shrink-0 border-b border-border p-2">
				<Input type="search" placeholder={searchPlaceholder} bind:value={search} />
			</div>
		{/if}
		<div class="min-h-0 flex-1 overflow-y-auto">
			{@render children()}
		</div>
	</div>
{/if}
