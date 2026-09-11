/**
 * Positioning and lifetime for anything that floats above the page. The
 * `Popover` component and the `tip` action are both thin shells over this.
 *
 * Why it exists. The popovers this replaces were absolutely positioned inside
 * the trigger's own box, which cost them twice:
 *
 *   - any ancestor with `overflow` other than `visible` clipped them. The parts
 *     table scrolls horizontally (`.pl-scroll`), so a panel opened from a row
 *     was cut off at the table's edge and turned the table into a scroller.
 *   - any ancestor that starts a stacking context painted over them, however
 *     high their own z-index went.
 *
 * Everything here is rendered into a layer appended to `<body>` (or to the open
 * `<dialog>`, which the browser paints in its own top layer above `<body>`
 * entirely) and positioned in viewport coordinates, so neither can happen. The
 * price is that the floating node is no longer a DOM descendant of its trigger,
 * which is why hover, focus and outside-click all have to be wired explicitly
 * by the callers.
 */

export type Side = 'top' | 'bottom' | 'left' | 'right';
export type Align = 'start' | 'center' | 'end';
export type Placement = Side | `${Side}-${Align}`;

const OPPOSITE: Record<Side, Side> = {
	top: 'bottom',
	bottom: 'top',
	left: 'right',
	right: 'left'
};

const VERTICAL = (side: Side) => side === 'top' || side === 'bottom';

/** Transparent band around the visible card, in px. */
export const INSET = 8;
/** How close to the viewport edge the card may come, in px. */
export const EDGE = 10;

/** Anything with a rect: an element, or a made-up box around the pointer. */
export interface Rectish {
	getBoundingClientRect(): DOMRect;
}

/**
 * A virtual anchor at the pointer. A tip on something wide (a whole table row)
 * pointing at the middle of it points at nothing in particular; pointing at the
 * cursor is what a tooltip has always done.
 */
export function pointerAnchor(x: number, y: number, pad = 6): Rectish {
	return {
		getBoundingClientRect: () =>
			new DOMRect(x - pad, y - pad, pad * 2, pad * 2)
	};
}

export function parsePlacement(placement: Placement): { side: Side; align: Align } {
	const [side, align] = placement.split('-') as [Side, Align | undefined];
	return { side, align: align ?? 'center' };
}

export interface PlaceOptions {
	placement?: Placement;
	/** Transparent band around the card. Doubles as the visual gap to the anchor. */
	inset?: number;
	/** Keep the card this far from the viewport edge. */
	edge?: number;
	/** Allow the side to change when the preferred one has no room. */
	flip?: boolean;
}

export interface Placed {
	side: Side;
	align: Align;
}

const clamp = (v: number, lo: number, hi: number) => (hi < lo ? lo : Math.min(Math.max(v, lo), hi));

/**
 * Position `layer` so that the card inside it sits next to `anchor`, and write
 * the result straight onto the two elements: a transform on the layer, the
 * space available to the card as custom properties, `data-side` for the arrow,
 * and `--pop-arrow` for where along that side the arrow points.
 *
 * Mutating rather than returning keeps the two callers from each re-deriving
 * the same handful of styles, and keeps the transparent-band width in one place
 * (it is both a padding and a term in the arithmetic, and they must agree).
 */
export function applyPlacement(
	anchor: Rectish,
	layer: HTMLElement,
	card: HTMLElement,
	opts: PlaceOptions = {}
): Placed {
	const { placement = 'bottom-start', inset = INSET, edge = EDGE, flip = true } = opts;
	const want = parsePlacement(placement);

	const vw = document.documentElement.clientWidth;
	const vh = document.documentElement.clientHeight;
	const a = anchor.getBoundingClientRect();

	layer.style.padding = `${inset}px`;
	layer.style.setProperty('--pop-inset', `${inset}px`);

	// Taking the height cap off below makes the card briefly not overflow, and a
	// browser clamps a non-overflowing element's scrollTop to 0. Put it back
	// afterwards or every reposition throws away how far down the reader was.
	const scrolled = card.scrollTop;

	// Natural size first: the constraint from the last run has to come off or
	// the card can only ever get smaller.
	card.style.setProperty('--pop-avail-w', '100vw');
	card.style.setProperty('--pop-avail-h', 'none');
	const natural = layer.getBoundingClientRect();

	// Room on each side of the anchor for the *card*, i.e. after the band and
	// the viewport edge margin are taken out.
	const room: Record<Side, number> = {
		top: a.top - inset - edge,
		bottom: vh - a.bottom - inset - edge,
		left: a.left - inset - edge,
		right: vw - a.right - inset - edge
	};

	const need = (side: Side) =>
		VERTICAL(side) ? natural.height - 2 * inset : natural.width - 2 * inset;

	let side = want.side;
	if (flip && room[side] < need(side)) {
		const other = OPPOSITE[side];
		// Flip only if the other side actually fits; otherwise stay where the
		// caller asked and let the card scroll, which is steadier than hopping
		// sides on every few pixels of scroll.
		if (room[other] >= need(other)) side = other;
		else if (room[other] > room[side]) side = other;
	}

	// Hand the card what is left, and let it cap its own width and scroll its
	// own overflow rather than being cut off by something upstream.
	if (VERTICAL(side)) {
		card.style.setProperty('--pop-avail-w', `${Math.max(vw - 2 * edge, 120)}px`);
		card.style.setProperty('--pop-avail-h', `${Math.max(room[side], 80)}px`);
	} else {
		card.style.setProperty('--pop-avail-w', `${Math.max(room[side], 140)}px`);
		card.style.setProperty('--pop-avail-h', `${Math.max(vh - 2 * edge, 80)}px`);
	}

	if (scrolled && card.scrollTop !== scrolled) card.scrollTop = scrolled;

	const box = layer.getBoundingClientRect();
	const w = box.width;
	const h = box.height;
	// The visible card, which is what alignment and edge margins are about.
	const cw = w - 2 * inset;
	const ch = h - 2 * inset;

	let x: number;
	let y: number;
	if (VERTICAL(side)) {
		// The band does the offsetting: the layer's edge sits flush against the
		// anchor so there is no dead pixel between them for the pointer to fall
		// through on its way to the card.
		y = side === 'bottom' ? a.bottom : a.top - h;
		x =
			want.align === 'start'
				? a.left - inset
				: want.align === 'end'
					? a.right - inset - cw
					: a.left + a.width / 2 - inset - cw / 2;
	} else {
		x = side === 'right' ? a.right : a.left - w;
		y =
			want.align === 'start'
				? a.top - inset
				: want.align === 'end'
					? a.bottom - inset - ch
					: a.top + a.height / 2 - inset - ch / 2;
	}

	x = clamp(x, edge - inset, vw - edge - inset - cw);
	y = clamp(y, edge - inset, vh - edge - inset - ch);

	// Where along the card the anchor's centre is, for the arrow. Kept a few px
	// off the corners so the arrow never hangs off the end of the card.
	const pad = inset + 8;
	const arrow = VERTICAL(side)
		? clamp(a.left + a.width / 2 - x, pad, w - pad)
		: clamp(a.top + a.height / 2 - y, pad, h - pad);

	layer.dataset.side = side;
	layer.style.setProperty('--pop-arrow', `${Math.round(arrow)}px`);
	layer.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;

	return { side, align: want.align };
}

/**
 * Whether the anchor is still worth pointing at: on screen, and not scrolled
 * out of sight inside a scroll container. Without this a fixed panel keeps
 * hanging in the viewport, pointing at nothing, after its row scrolls away.
 */
export function anchorVisible(anchor: Element): boolean {
	const a = anchor.getBoundingClientRect();
	if (!a.width && !a.height) return false;
	const vw = document.documentElement.clientWidth;
	const vh = document.documentElement.clientHeight;
	if (a.bottom <= 0 || a.top >= vh || a.right <= 0 || a.left >= vw) return false;

	for (let el = anchor.parentElement; el && el !== document.body; el = el.parentElement) {
		const style = getComputedStyle(el);
		if (style.overflowX === 'visible' && style.overflowY === 'visible') continue;
		const r = el.getBoundingClientRect();
		if (a.bottom <= r.top || a.top >= r.bottom || a.right <= r.left || a.left >= r.right) return false;
	}
	return true;
}

/**
 * The element to render into. A `<dialog>` opened with `showModal()` is painted
 * in the browser's top layer, above every z-index on the page, so a panel for an
 * anchor inside one has to live in the dialog or it is simply invisible.
 */
export function layerHost(anchor: Element): HTMLElement {
	return (anchor.closest('dialog[open]') as HTMLElement | null) ?? document.body;
}

/**
 * Re-run `update` whenever anything could have moved the anchor. `scroll` is
 * captured so it catches every scroll container on the way down, not just the
 * window.
 */
export function autoUpdate(anchor: Element, card: Element, update: () => void): () => void {
	let frame = 0;
	const schedule = () => {
		if (frame) return;
		frame = requestAnimationFrame(() => {
			frame = 0;
			update();
		});
	};

	// A wheel inside the panel is a scroll event like any other, and it reaches
	// this capture listener before anything else. Repositioning on it is both
	// pointless (the anchor has not moved) and destructive, so skip our own.
	const onScroll = (e: Event) => {
		const t = e.target as Node | null;
		if (t && t.nodeType === 1 && (t === card || card.contains(t))) return;
		schedule();
	};

	const scrollOpts: AddEventListenerOptions = { passive: true, capture: true };
	window.addEventListener('scroll', onScroll, scrollOpts);
	window.addEventListener('resize', schedule, { passive: true });

	// The anchor can move without a scroll (a row expanding above it), and the
	// card can grow when an image inside it loads.
	const ro = new ResizeObserver(schedule);
	ro.observe(anchor);
	ro.observe(card);

	return () => {
		if (frame) cancelAnimationFrame(frame);
		window.removeEventListener('scroll', onScroll, scrollOpts);
		window.removeEventListener('resize', schedule);
		ro.disconnect();
	};
}

/* ── One at a time ──────────────────────────────────────────────────────── */

interface OpenEntry {
	panel: HTMLElement;
	close: () => void;
}

let openPopover: OpenEntry | null = null;
let hideTip: (() => void) | null = null;

/**
 * Register a popover as the open one, closing whichever was open before it.
 * A trigger sitting *inside* the open panel is left alone, so a popover nested
 * in another one does not shut its own parent.
 */
export function claimOpen(panel: HTMLElement, anchor: Element, close: () => void): () => void {
	if (openPopover && openPopover.panel !== panel && !openPopover.panel.contains(anchor)) {
		openPopover.close();
	}
	// A popover and a hover tip on screen together is the overlap in the report.
	hideTip?.();
	const entry: OpenEntry = { panel, close };
	openPopover = entry;
	return () => {
		if (openPopover === entry) openPopover = null;
	};
}

/** Let the tip layer make itself dismissable by an opening popover. */
export function registerTipCloser(close: () => void) {
	hideTip = close;
}

/** True while a popover is open under the pointer. Tips stay quiet then. */
export function popoverOpenOver(node: Element): boolean {
	return !!openPopover && (openPopover.panel.contains(node) || openPopover.panel === node);
}

export function anyPopoverOpen(): boolean {
	return !!openPopover;
}
