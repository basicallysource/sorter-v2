// Reads colors as the browser draws them, for the color page: whatever a
// token resolves to (a hex, a color-mix, a translucent tint over a plane),
// resolved by the browser on an element and painted onto one canvas pixel.

let context: CanvasRenderingContext2D | null = null;

function pixel(): CanvasRenderingContext2D {
	if (!context) {
		const canvas = document.createElement('canvas');
		canvas.width = 1;
		canvas.height = 1;
		context = canvas.getContext('2d', { willReadFrequently: true })!;
	}
	return context;
}

/** The color `css` as drawn over `base`, as a hex string ('' if the canvas
 *  cannot read it). */
export function drawn(css: string, base = '#ffffff'): string {
	const ctx = pixel();
	ctx.clearRect(0, 0, 1, 1);
	ctx.fillStyle = base;
	ctx.fillRect(0, 0, 1, 1);
	ctx.fillStyle = '#010203';
	ctx.fillStyle = css;
	if (ctx.fillStyle === '#010203' && css.replace(/\s/g, '') !== '#010203') return '';
	ctx.fillRect(0, 0, 1, 1);
	const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
	return '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('');
}

/** A token's color as the browser resolves it inside `within` (so in that
 *  element's mode), e.g. resolved(column, 'primary-soft'). */
export function resolved(within: Element, token: string): string {
	const probe = document.createElement('span');
	probe.style.backgroundColor = `var(--${token})`;
	within.appendChild(probe);
	const color = getComputedStyle(probe).backgroundColor;
	probe.remove();
	return color;
}
