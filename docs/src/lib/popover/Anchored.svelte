<script lang="ts">
	import type { Snippet } from 'svelte';
	import {
		anchorVisible,
		applyPlacement,
		autoUpdate,
		layerHost,
		type Placement
	} from './floating';
	import './popover.css';

	/**
	 * The floating layer with no opinion about what goes in it: a menu, a colour
	 * grid, anything that has to hang off a control and stay whole. `Popover` is
	 * this plus the hover behaviour and the card chrome; reach for this one when
	 * the panel is a control rather than an explanation, and keeps its own look.
	 *
	 * Open/closed is the caller's state (a menu opens on click, not on hover).
	 * Dismissal is not, because only this component knows where the panel ended
	 * up once it left the DOM next to its trigger.
	 */
	let {
		anchor,
		placement = 'bottom-start',
		inset = 4,
		maxHeight,
		class: cls = '',
		onDismiss,
		children
	}: {
		anchor: HTMLElement | null | undefined;
		placement?: Placement;
		/** Gap to the trigger. Doubles as the transparent bridge for the pointer. */
		inset?: number;
		/** Cap the panel's own height. It still shrinks further to fit the screen. */
		maxHeight?: string;
		class?: string;
		onDismiss?: () => void;
		children: Snippet;
	} = $props();

	let layer = $state<HTMLElement | null>(null);
	let card = $state<HTMLElement | null>(null);

	function portal(node: HTMLElement) {
		layerHost(anchor ?? node).appendChild(node);
		return {
			destroy() {
				node.remove();
			}
		};
	}

	$effect(() => {
		if (!anchor || !layer || !card) return;
		const a = anchor;
		const el = layer;
		const inner = card;

		const update = () => {
			if (!anchorVisible(a)) {
				onDismiss?.();
				return;
			}
			applyPlacement(a, el, inner, { placement, inset });
		};
		update();
		const frame = requestAnimationFrame(update);
		const stop = autoUpdate(a, inner, update);

		const onPointerDown = (e: Event) => {
			const t = e.target as Node;
			if (a.contains(t) || el.contains(t)) return;
			onDismiss?.();
		};
		const onKey = (e: KeyboardEvent) => {
			if (e.key === 'Escape') onDismiss?.();
		};
		document.addEventListener('pointerdown', onPointerDown, true);
		document.addEventListener('keydown', onKey);

		return () => {
			cancelAnimationFrame(frame);
			stop();
			document.removeEventListener('pointerdown', onPointerDown, true);
			document.removeEventListener('keydown', onKey);
		};
	});
</script>

<div bind:this={layer} use:portal class="pop-layer" data-interactive="true">
	<div bind:this={card} class="pop-anchored {cls}" style:--pop-h={maxHeight}>{@render children()}</div>
</div>
