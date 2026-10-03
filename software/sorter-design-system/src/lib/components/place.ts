// Where a floating panel goes (docs/overlays.md): next to its anchor on the
// preferred side, flipped to the other side when that one has no room, and
// kept 8px inside the window. Popover, Menu and Tooltip share it. They render
// in the browser's top layer (the popover attribute), so no ancestor's
// overflow can clip them and no z-index is needed.

export type Side = 'top' | 'bottom' | 'left' | 'right';
export type Placement = Side | `${'top' | 'bottom'}-${'start' | 'end'}`;

const MARGIN = 8;

export function place(
	anchor: DOMRect,
	panel: { width: number; height: number },
	placement: Placement,
	gap = 6
): { top: number; left: number; side: Side } {
	const vw = window.innerWidth;
	const vh = window.innerHeight;
	let [side, align] = placement.split('-') as [Side, 'start' | 'end' | undefined];

	const room = {
		top: anchor.top - gap - MARGIN,
		bottom: vh - anchor.bottom - gap - MARGIN,
		left: anchor.left - gap - MARGIN,
		right: vw - anchor.right - gap - MARGIN
	};
	const flip = { top: 'bottom', bottom: 'top', left: 'right', right: 'left' } as const;
	const need = side === 'top' || side === 'bottom' ? panel.height : panel.width;
	if (room[side] < need && room[flip[side]] > room[side]) side = flip[side];

	let top: number;
	let left: number;
	if (side === 'top' || side === 'bottom') {
		top = side === 'bottom' ? anchor.bottom + gap : anchor.top - gap - panel.height;
		left =
			align === 'start'
				? anchor.left
				: align === 'end'
					? anchor.right - panel.width
					: anchor.left + anchor.width / 2 - panel.width / 2;
	} else {
		left = side === 'right' ? anchor.right + gap : anchor.left - gap - panel.width;
		top = anchor.top + anchor.height / 2 - panel.height / 2;
	}

	return {
		top: clamp(top, MARGIN, vh - MARGIN - panel.height),
		left: clamp(left, MARGIN, vw - MARGIN - panel.width),
		side
	};
}

function clamp(value: number, min: number, max: number) {
	return Math.max(min, Math.min(value, Math.max(min, max)));
}
