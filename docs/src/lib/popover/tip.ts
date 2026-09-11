import {
	anchorVisible,
	anyPopoverOpen,
	applyPlacement,
	autoUpdate,
	layerHost,
	pointerAnchor,
	popoverOpenOver,
	registerTipCloser,
	type Placement,
	type Rectish
} from './floating';
import './popover.css';

/**
 * `use:tip` — a short label on hover or focus, in place of a native `title`.
 *
 * The browser's own tooltip is the other half of the report: it renders above
 * absolutely everything, on its own schedule, so it can and does land on top of
 * an open popover (a `title` on a thumbnail button, a popover open from the
 * badge in the same tile). It also cannot be styled, cannot be dismissed, and
 * never shows on touch. This is the same information, drawn in the same layer
 * as everything else that floats, and it stays out of the way while a popover
 * is open.
 *
 *     <button use:tip={'Frame the whole part again'}>…</button>
 *     <span use:tip={{ text: long, placement: 'top', wide: true }}>…</span>
 *
 * With no argument it takes over the element's own `title`, which makes
 * converting an existing one a single attribute change.
 */

export interface TipOptions {
	text?: string | null;
	placement?: Placement;
	/** Room for a sentence rather than a label. */
	wide?: boolean;
	delay?: number;
}

export type TipParam = string | null | undefined | TipOptions;

const DELAY = 200;
/**
 * Wider than this and the element is not a thing to point at: a table row, a
 * full-width link. Those anchor to the cursor instead, and wait longer, because
 * the pointer crosses them while reading rather than to ask a question.
 */
const WIDE = 360;
const WIDE_DELAY = 550;

let layer: HTMLElement | null = null;
let card: HTMLElement | null = null;
let owner: HTMLElement | null = null;
let stopUpdate: (() => void) | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let seq = 0;
let pointer = { x: 0, y: 0 };

function normalise(param: TipParam, node: HTMLElement): TipOptions {
	const opts = typeof param === 'string' || param == null ? { text: param ?? undefined } : param;
	return { ...opts, text: opts.text ?? node.dataset.tipTitle ?? '' };
}

function build(): { layer: HTMLElement; card: HTMLElement } {
	if (layer && card) return { layer, card };
	layer = document.createElement('div');
	layer.className = 'pop-layer';
	layer.dataset.tone = 'tip';
	layer.dataset.interactive = 'false';
	layer.hidden = true;

	card = document.createElement('div');
	card.className = 'pop-card';
	card.id = 'pop-tip';
	card.setAttribute('role', 'tooltip');

	const arrow = document.createElement('span');
	arrow.className = 'pop-arrow';
	arrow.setAttribute('aria-hidden', 'true');

	layer.append(card, arrow);
	return { layer, card };
}

function hide() {
	clearTimeout(timer);
	timer = undefined;
	stopUpdate?.();
	stopUpdate = null;
	owner?.removeAttribute('aria-describedby');
	owner = null;
	if (!layer) return;
	layer.hidden = true;
	layer.remove();
}

registerTipCloser(hide);

function show(node: HTMLElement, opts: TipOptions) {
	const text = opts.text?.trim();
	if (!text) return;
	// While a popover is open, the only tips worth showing are the ones inside
	// it. Anything else is the overlap this replaced.
	if (anyPopoverOpen() && !popoverOpenOver(node)) return;

	hide();
	const built = build();
	built.card.textContent = text;
	built.card.id = `pop-tip-${++seq}`;
	built.layer.dataset.wide = opts.wide ? 'true' : 'false';
	built.layer.hidden = false;
	layerHost(node).appendChild(built.layer);

	owner = node;
	node.setAttribute('aria-describedby', built.card.id);

	const wide = node.getBoundingClientRect().width > WIDE;
	const update = () => {
		if (!anchorVisible(node)) {
			hide();
			return;
		}
		const target: Rectish = wide ? pointerAnchor(pointer.x, pointer.y) : node;
		applyPlacement(target, built.layer, built.card, {
			placement: opts.placement ?? 'bottom',
			inset: 6
		});
	};
	update();
	stopUpdate = autoUpdate(node, built.card, update);
}

export function tip(node: HTMLElement, param?: TipParam) {
	let opts = normalise(param, node);

	// Take the native tooltip off the element: two tooltips for one thing is
	// exactly what this is here to stop. Keep the text so `use:tip` with no
	// argument still has something to say.
	const native = node.getAttribute('title');
	if (native) {
		node.dataset.tipTitle = native;
		node.removeAttribute('title');
		opts = normalise(param, node);
	}

	// An icon-only control whose only name was its `title` would otherwise go
	// nameless; anything already named gets described, not renamed.
	const named = node.hasAttribute('aria-label') || node.hasAttribute('aria-labelledby');
	if (!named && !node.textContent?.trim() && opts.text) node.setAttribute('aria-label', opts.text);

	const onEnter = (e: PointerEvent) => {
		if (e.pointerType === 'touch') return;
		pointer = { x: e.clientX, y: e.clientY };
		clearTimeout(timer);
		const wide = node.getBoundingClientRect().width > WIDE;
		timer = setTimeout(() => show(node, opts), opts.delay ?? (wide ? WIDE_DELAY : DELAY));
	};
	const onMove = (e: PointerEvent) => {
		pointer = { x: e.clientX, y: e.clientY };
	};
	const onLeave = () => {
		if (owner === node || timer) hide();
	};
	const onFocus = () => show(node, opts);
	const onKey = (e: KeyboardEvent) => {
		if (e.key === 'Escape' && owner === node) hide();
	};

	node.addEventListener('pointerenter', onEnter);
	node.addEventListener('pointermove', onMove, { passive: true });
	node.addEventListener('pointerleave', onLeave);
	node.addEventListener('pointerdown', onLeave);
	node.addEventListener('focus', onFocus);
	node.addEventListener('blur', onLeave);
	node.addEventListener('keydown', onKey);

	return {
		update(next: TipParam) {
			opts = normalise(next, node);
			if (owner === node && card) card.textContent = opts.text?.trim() ?? '';
		},
		destroy() {
			node.removeEventListener('pointerenter', onEnter);
			node.removeEventListener('pointermove', onMove);
			node.removeEventListener('pointerleave', onLeave);
			node.removeEventListener('pointerdown', onLeave);
			node.removeEventListener('focus', onFocus);
			node.removeEventListener('blur', onLeave);
			node.removeEventListener('keydown', onKey);
			if (owner === node) hide();
		}
	};
}

/**
 * `use:tipScope` — the same tips inside a block of HTML this app did not write
 * the markup for.
 *
 * The docs render markdown (and hand-written HTML in it) with `{@html}`, so
 * there is no element to hang `use:tip` on. Mark those up with `data-tip="…"`
 * and put this on the container: every marked descendant gets a tip, including
 * ones that appear later, since the content is replaced wholesale on
 * navigation.
 */
export function tipScope(node: HTMLElement) {
	const live = new Map<HTMLElement, { destroy(): void }>();

	const scan = () => {
		const found = new Set<HTMLElement>();
		for (const el of node.querySelectorAll<HTMLElement>('[data-tip]')) {
			found.add(el);
			if (!live.has(el)) live.set(el, tip(el, el.dataset.tip));
		}
		for (const [el, handle] of live) {
			if (found.has(el)) continue;
			handle.destroy();
			live.delete(el);
		}
	};

	scan();
	const mo = new MutationObserver(scan);
	mo.observe(node, { childList: true, subtree: true });

	return {
		destroy() {
			mo.disconnect();
			for (const handle of live.values()) handle.destroy();
			live.clear();
		}
	};
}
