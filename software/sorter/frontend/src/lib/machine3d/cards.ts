// The card on each bin's front: what it says, and how it is drawn. Every
// card of a style is drawn into one texture (an atlas); the view shows each on
// one instanced quad, so the cards cost no DOM and sit behind what is in front
// of them like any other surface.

export type CardStyle = 'paper' | 'plate' | 'panel' | 'pieces' | 'stencil' | 'number';

export type CardShape = {
	name: CardStyle;
	label: string;
	// The card's width over its height.
	aspect: number;
	// Its width, as a share of the bin's front; and where its centre is, as a
	// share of the bin's height from its base.
	width: number;
	lift: number;
	// How far in front of the bin it sits (metres).
	offset: number;
};

export const CARD_STYLES: CardShape[] = [
	{ name: 'paper', label: 'Now', aspect: 4, width: 0.86, lift: 0.32, offset: 0.002 },
	{ name: 'plate', label: 'Nameplate', aspect: 5, width: 0.96, lift: 0.2, offset: 0.0006 },
	{ name: 'panel', label: 'Panel with colours', aspect: 3, width: 0.9, lift: 0.3, offset: 0.0008 },
	{ name: 'pieces', label: 'Recent pieces', aspect: 2.2, width: 0.92, lift: 0.36, offset: 0.0008 },
	{ name: 'stencil', label: 'Printed on', aspect: 4, width: 0.92, lift: 0.22, offset: 0.0004 },
	{ name: 'number', label: 'Number only', aspect: 1.25, width: 0.3, lift: 0.26, offset: 0.0008 }
];

/** What one bin's card can show. */
export type CardData = {
	name: string;
	// Where it is, as the Bins page writes it (layer, section, bin from 1).
	code: string;
	number: string;
	// The colours of the pieces that went in last, newest first.
	colors: string[];
	// Pictures of those pieces, newest first; null where there is none.
	images: (CanvasImageSource | null)[];
};

export type CardTheme = {
	surface: string;
	well: string;
	ink: string;
	inkMuted: string;
	primary: string;
	primarySoft: string;
	// Text that reads on the bins' own colour, for the cards printed on them.
	onBin?: string;
};

const CELL_HEIGHT = 80;
const MAX_WIDTH = 4096;

export type Atlas = { canvas: HTMLCanvasElement; columns: number; rows: number };

/** Every bin's card in one picture: cell `i` is at column i % columns, row
 *  floor(i / columns), from the top left. */
export function drawCards(shape: CardShape, cards: CardData[], t: CardTheme): Atlas {
	const h = CELL_HEIGHT;
	const w = Math.round(h * shape.aspect);
	const columns = Math.max(1, Math.min(cards.length, Math.floor(MAX_WIDTH / w)));
	const rows = Math.max(1, Math.ceil(cards.length / columns));
	const canvas = document.createElement('canvas');
	canvas.width = w * columns;
	canvas.height = h * rows;
	const g = canvas.getContext('2d')!;
	const font = getComputedStyle(document.body).fontFamily || 'sans-serif';
	g.textBaseline = 'middle';
	cards.forEach((c, i) => {
		const x = (i % columns) * w;
		const y = Math.floor(i / columns) * h;
		g.save();
		g.beginPath();
		g.rect(x, y, w, h);
		g.clip();
		draw[shape.name](g, c, { x, y, w, h }, t, font);
		g.restore();
	});
	return { canvas, columns, rows };
}

type Box = { x: number; y: number; w: number; h: number };
type Draw = (g: CanvasRenderingContext2D, c: CardData, b: Box, t: CardTheme, font: string) => void;

const draw: Record<CardStyle, Draw> = {
	// The first try: the name on a white card.
	paper(g, c, b, t, font) {
		if (!c.name) return;
		g.fillStyle = t.surface;
		g.fillRect(b.x, b.y, b.w, b.h);
		g.fillStyle = t.ink;
		g.font = `500 26px ${font}`;
		lines(g, c.name, b.w - 24, 2).forEach((line, n, all) =>
			g.fillText(line, b.x + 12, b.y + b.h / 2 + (n - (all.length - 1) / 2) * 30)
		);
	},
	// A dark plate across the front, like an engraved label: the name, and the
	// bin's number at the right.
	plate(g, c, b, t, font) {
		g.fillStyle = t.ink;
		g.fillRect(b.x, b.y, b.w, b.h);
		g.fillStyle = t.surface;
		g.font = `600 30px ${font}`;
		const num = c.number;
		g.textAlign = 'right';
		g.globalAlpha = 0.6;
		g.fillText(num, b.x + b.w - 16, b.y + b.h / 2);
		g.globalAlpha = 1;
		const room = b.w - 32 - g.measureText(num).width - 16;
		g.textAlign = 'left';
		g.font = `500 28px ${font}`;
		g.fillText(fit(g, c.name || 'No category', room), b.x + 16, b.y + b.h / 2);
	},
	// The app's own panel: the name, where the bin is, and a dot for the colour
	// of each piece that went in last.
	panel(g, c, b, t, font) {
		g.fillStyle = t.surface;
		g.fillRect(b.x, b.y, b.w, b.h);
		g.fillStyle = t.ink;
		g.font = `600 24px ${font}`;
		g.fillText(fit(g, c.name || 'No category', b.w - 28), b.x + 14, b.y + 22);
		g.fillStyle = t.inkMuted;
		g.font = `400 18px ${font}`;
		g.fillText(c.code, b.x + 14, b.y + 50);
		const r = 7;
		const colors = c.colors.slice(0, 8);
		colors.forEach((color, n) => {
			g.fillStyle = color;
			g.beginPath();
			g.arc(
				b.x + b.w - 16 - r - (colors.length - 1 - n) * (r * 2 + 5),
				b.y + 50,
				r,
				0,
				Math.PI * 2
			);
			g.fill();
		});
	},
	// The name over pictures of the pieces that went in last.
	pieces(g, c, b, t, font) {
		g.fillStyle = t.surface;
		g.fillRect(b.x, b.y, b.w, b.h);
		g.fillStyle = t.ink;
		g.font = `600 20px ${font}`;
		g.fillText(fit(g, c.name || 'No category', b.w - 20), b.x + 10, b.y + 16);
		const size = b.h - 36;
		const count = Math.floor((b.w - 10) / (size + 6));
		for (let n = 0; n < count; n++) {
			const sx = b.x + 10 + n * (size + 6);
			const sy = b.y + 30;
			g.fillStyle = t.well;
			g.fillRect(sx, sy, size, size);
			const img = c.images[n];
			if (img) contain(g, img, sx + 2, sy + 2, size - 4, size - 4);
			else if (c.colors[n]) {
				g.fillStyle = c.colors[n];
				g.fillRect(sx + size * 0.25, sy + size * 0.25, size * 0.5, size * 0.5);
			}
		}
	},
	// The name printed straight on the bin, no card at all.
	stencil(g, c, b, t, font) {
		if (!c.name) return;
		g.fillStyle = t.onBin ?? t.ink;
		g.font = `700 30px ${font}`;
		g.textAlign = 'center';
		g.fillText(fit(g, c.name, b.w - 16), b.x + b.w / 2, b.y + b.h / 2);
	},
	// Only the bin's number, in the primary's tint; the name is in the panel.
	number(g, c, b, t, font) {
		g.fillStyle = t.primarySoft;
		g.fillRect(b.x, b.y, b.w, b.h);
		g.fillStyle = t.primary;
		g.font = `700 44px ${font}`;
		g.textAlign = 'center';
		g.fillText(c.number, b.x + b.w / 2, b.y + b.h / 2 + 2);
	}
};

function fit(g: CanvasRenderingContext2D, text: string, width: number): string {
	if (g.measureText(text).width <= width) return text;
	let s = text;
	while (s.length > 1 && g.measureText(`${s}…`).width > width) s = s.slice(0, -1);
	return `${s}…`;
}

function lines(g: CanvasRenderingContext2D, text: string, width: number, max: number): string[] {
	const out: string[] = [];
	let line = '';
	for (const word of text.split(/\s+/)) {
		const next = line ? `${line} ${word}` : word;
		if (g.measureText(next).width <= width || !line) line = next;
		else {
			out.push(line);
			line = word;
		}
	}
	if (line) out.push(line);
	if (out.length > max) {
		out.length = max;
		out[max - 1] = fit(g, `${out[max - 1]}…`, width);
	}
	return out.map((l) => fit(g, l, width));
}

function contain(
	g: CanvasRenderingContext2D,
	img: CanvasImageSource,
	x: number,
	y: number,
	w: number,
	h: number
) {
	const iw = (img as { width: number }).width || w;
	const ih = (img as { height: number }).height || h;
	const k = Math.min(w / iw, h / ih);
	g.drawImage(img, x + (w - iw * k) / 2, y + (h - ih * k) / 2, iw * k, ih * k);
}
