<script lang="ts">
	import type { Snippet } from 'svelte';
	import {
		anchorVisible,
		applyPlacement,
		autoUpdate,
		claimOpen,
		layerHost,
		type Placement
	} from './floating';
	import './popover.css';

	/**
	 * Context help attached to something on the page: hover it to peek, click to
	 * pin it open, Escape or a click elsewhere to dismiss. Content is a `text`
	 * string or a `children` snippet; the trigger is an info dot unless a
	 * `trigger` snippet supplies one.
	 *
	 * Three things it does that the hand-rolled version did not:
	 *
	 *   - the panel is rendered into a layer at the end of the document, so no
	 *     ancestor's `overflow` can clip it and no ancestor's stacking context can
	 *     paint over it.
	 *   - the panel is flush against the trigger (its outer 8 px are transparent),
	 *     and closing is delayed, so moving the pointer onto it cannot fall
	 *     through a gap and dismiss it half way.
	 *   - it flips and slides to stay on screen, and scrolls its own overflow when
	 *     there is not enough room, instead of running off the edge.
	 *
	 * `class` replaces the root's own classes, for a trigger that has to sit
	 * somewhere specific (a corner mark on an image tile). The root no longer has
	 * to be a containing block for the panel, but it is still what the panel is
	 * measured against, so anything that moves the trigger moves this element.
	 */
	let {
		text = '',
		label = 'More information',
		placement = 'bottom-start',
		width = '18rem',
		tone = 'panel',
		openDelay = 60,
		closeDelay = 220,
		class: cls = 'inline-flex align-middle',
		children,
		trigger
	}: {
		text?: string;
		label?: string;
		placement?: Placement;
		/** Preferred card width, any CSS length. It still shrinks to fit. */
		width?: string;
		tone?: 'panel' | 'tip';
		openDelay?: number;
		closeDelay?: number;
		class?: string;
		children?: Snippet;
		trigger?: Snippet<[{ toggle: () => void; open: boolean; props: Record<string, unknown> }]>;
	} = $props();

	let open = $state(false);
	let pinned = $state(false);
	let root = $state<HTMLElement | null>(null);
	let layer = $state<HTMLElement | null>(null);
	let card = $state<HTMLElement | null>(null);

	const uid = $props.id();
	const panelId = `pop-${uid}`;
	let openTimer: ReturnType<typeof setTimeout> | undefined;
	let closeTimer: ReturnType<typeof setTimeout> | undefined;

	function show(now = false) {
		clearTimeout(closeTimer);
		closeTimer = undefined;
		if (open) return;
		if (now) {
			clearTimeout(openTimer);
			openTimer = undefined;
			open = true;
			return;
		}
		if (openTimer) return;
		openTimer = setTimeout(() => {
			openTimer = undefined;
			open = true;
		}, openDelay);
	}

	function hide(now = false) {
		clearTimeout(openTimer);
		openTimer = undefined;
		if (now) {
			clearTimeout(closeTimer);
			closeTimer = undefined;
			pinned = false;
			open = false;
			return;
		}
		if (pinned || !open || closeTimer) return;
		// The grace period is what lets the pointer take a diagonal route onto the
		// panel, and what makes a badge you brushed past not flash at you.
		closeTimer = setTimeout(() => {
			closeTimer = undefined;
			open = false;
		}, closeDelay);
	}

	function toggle() {
		if (pinned) {
			pinned = false;
			open = false;
		} else {
			pinned = true;
			show(true);
		}
	}

	function onEnter(e: PointerEvent) {
		if (e.pointerType === 'touch') return; // a tap is a click, not a hover
		show();
	}

	function onLeave(e: PointerEvent) {
		if (e.pointerType === 'touch') return;
		hide();
	}

	// Focus opens it too, so it is reachable without a pointer. Moving focus into
	// the panel (a link in a planned-change notice) must not close it, and the
	// panel is not a DOM descendant any more, so containment is checked by hand.
	function onFocusIn() {
		show(true);
	}

	function onFocusOut(e: FocusEvent) {
		const to = e.relatedTarget as Node | null;
		if (to && (root?.contains(to) || layer?.contains(to))) return;
		hide(true);
	}

	/** Move the panel into the layer that nothing on the page can clip. */
	function portal(node: HTMLElement) {
		layerHost(root ?? node).appendChild(node);
		return {
			destroy() {
				node.remove();
			}
		};
	}

	$effect(() => {
		if (!open || !root || !layer || !card) return;
		const anchor = root;
		const el = layer;
		const inner = card;

		const update = () => {
			if (!anchorVisible(anchor)) {
				// Its row scrolled out from under it: a panel pointing at nothing is
				// worse than no panel.
				hide(true);
				return;
			}
			applyPlacement(anchor, el, inner, { placement });
		};

		update();
		// Second pass after layout settles (web fonts, an image in the panel).
		const frame = requestAnimationFrame(update);
		const stopUpdate = autoUpdate(anchor, inner, update);
		const release = claimOpen(el, anchor, () => hide(true));

		const onDocPointerDown = (e: Event) => {
			const t = e.target as Node;
			if (anchor.contains(t) || el.contains(t)) return;
			hide(true);
		};
		const onKey = (e: KeyboardEvent) => {
			if (e.key !== 'Escape') return;
			const active = document.activeElement;
			hide(true);
			if (active && el.contains(active)) (anchor.querySelector('button, a') as HTMLElement)?.focus();
		};

		document.addEventListener('pointerdown', onDocPointerDown, true);
		document.addEventListener('keydown', onKey);

		return () => {
			cancelAnimationFrame(frame);
			stopUpdate();
			release();
			document.removeEventListener('pointerdown', onDocPointerDown, true);
			document.removeEventListener('keydown', onKey);
		};
	});

	$effect(() => () => {
		clearTimeout(openTimer);
		clearTimeout(closeTimer);
	});

	const triggerProps = $derived({
		'aria-expanded': open,
		'aria-describedby': open ? panelId : undefined
	});
</script>

<span
	bind:this={root}
	class={cls}
	onpointerenter={onEnter}
	onpointerleave={onLeave}
	onfocusin={onFocusIn}
	onfocusout={onFocusOut}
	role="presentation"
>
	{#if trigger}
		{@render trigger({ toggle, open, props: triggerProps })}
	{:else}
		<button
			type="button"
			class="pop-dot"
			aria-label={label}
			aria-expanded={open}
			aria-describedby={open ? panelId : undefined}
			onclick={toggle}
		>
			<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" />
			</svg>
		</button>
	{/if}
</span>

{#if open}
	<div
		bind:this={layer}
		use:portal
		class="pop-layer"
		data-tone={tone}
		data-interactive="true"
		style:--pop-w={width}
		onpointerenter={() => {
			clearTimeout(closeTimer);
			closeTimer = undefined;
		}}
		onpointerleave={onLeave}
		onfocusout={onFocusOut}
		role="presentation"
	>
		<div bind:this={card} class="pop-card" id={panelId} role="tooltip" aria-label={label}>
			{#if children}{@render children()}{:else}{text}{/if}
		</div>
		<span class="pop-arrow" aria-hidden="true"></span>
	</div>
{/if}

<style>
	.pop-dot {
		display: inline-flex;
		align-items: center;
		color: var(--color-text-muted, #6b6862);
		cursor: help;
		transition: color 0.12s ease;
	}

	.pop-dot:hover,
	.pop-dot[aria-expanded='true'] {
		color: var(--color-text, #1a1a1a);
	}
</style>
