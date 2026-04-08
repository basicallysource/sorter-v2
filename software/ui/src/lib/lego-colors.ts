/**
 * Curated LEGO color palette for the Sorter UI primary-color picker.
 *
 * 40 canonical solid-opaque LEGO colors with their official BrickLink /
 * Rebrickable hex values (sourced from Rebrickable's public colors.csv —
 * the same data used by every LEGO inventory tool out there). Hex codes
 * themselves are factual data and not copyrightable; the color *names*
 * are the de-facto community names that map cleanly to the BrickLink
 * catalog. Sorted by hue family.
 *
 * Excluded by intent: Trans-*, Metallic, Chrome, Pearl, Glitter, Speckle,
 * Modulex, Duplo-only, and Fabuland one-offs. Also excluded: any color
 * so light it can't carry text in either contrast direction (White,
 * Light Bluish Gray, Light Tan, Bright Light Yellow, Lavender pastel).
 *
 * Each entry carries:
 *   id        — stable slug used for persistence and lookup
 *   name      — display name shown in the picker (matches BrickLink)
 *   hex       — canonical BrickLink/Rebrickable hex
 *   hover     — pressed/hover state, computed as hex × 0.80
 *   dark      — dark twin for tinted backgrounds, computed as hex × 0.45
 *   contrast  — readable text-on-color: 'white' or 'black'
 *                (chosen by WCAG-style relative luminance, threshold 0.30)
 *
 * The default is `blue` (LEGO Blue, #0055BF), which matches the existing
 * hardcoded primary across the UI and is the most iconic LEGO color.
 */

export type LegoColor = {
	id: string;
	name: string;
	hex: string;
	hover: string;
	dark: string;
	contrast: 'white' | 'black';
};

export const DEFAULT_COLOR_ID = 'blue';

export const LEGO_COLORS: readonly LegoColor[] = [
	// ── Reds ─────────────────────────────────────────────────────────────────
	{ id: 'red', name: 'Red', hex: '#C91A09', hover: '#A11507', dark: '#5A0C04', contrast: 'white' },
	{ id: 'dark-red', name: 'Dark Red', hex: '#720E0F', hover: '#5B0B0C', dark: '#330607', contrast: 'white' },
	{ id: 'rust', name: 'Rust', hex: '#B31004', hover: '#8F0D03', dark: '#510702', contrast: 'white' },

	// ── Pinks & corals ───────────────────────────────────────────────────────
	{ id: 'coral', name: 'Coral', hex: '#FF698F', hover: '#CC5472', dark: '#732F40', contrast: 'black' },
	{ id: 'dark-pink', name: 'Dark Pink', hex: '#C870A0', hover: '#A05A80', dark: '#5A3248', contrast: 'white' },
	{ id: 'magenta', name: 'Magenta', hex: '#923978', hover: '#752E60', dark: '#421A36', contrast: 'white' },
	{ id: 'medium-dark-pink', name: 'Medium Dark Pink', hex: '#F785B1', hover: '#C66A8E', dark: '#6F3C50', contrast: 'black' },

	// ── Purples ──────────────────────────────────────────────────────────────
	{ id: 'purple', name: 'Purple', hex: '#81007B', hover: '#670062', dark: '#3A0037', contrast: 'white' },
	{ id: 'dark-purple', name: 'Dark Purple', hex: '#3F3691', hover: '#322B74', dark: '#1C1841', contrast: 'white' },
	{ id: 'medium-lavender', name: 'Medium Lavender', hex: '#AC78BA', hover: '#8A6095', dark: '#4D3654', contrast: 'white' },
	{ id: 'medium-violet', name: 'Medium Violet', hex: '#9391E4', hover: '#7674B6', dark: '#424167', contrast: 'black' },

	// ── Blues ────────────────────────────────────────────────────────────────
	{ id: 'blue', name: 'Blue', hex: '#0055BF', hover: '#004499', dark: '#002656', contrast: 'white' },
	{ id: 'dark-blue', name: 'Dark Blue', hex: '#0A3463', hover: '#082A4F', dark: '#04172D', contrast: 'white' },
	{ id: 'medium-blue', name: 'Medium Blue', hex: '#5A93DB', hover: '#4876AF', dark: '#284263', contrast: 'white' },
	{ id: 'sand-blue', name: 'Sand Blue', hex: '#6074A1', hover: '#4D5D81', dark: '#2B3448', contrast: 'white' },
	{ id: 'maersk-blue', name: 'Maersk Blue', hex: '#3592C3', hover: '#2A759C', dark: '#184258', contrast: 'white' },
	{ id: 'dark-azure', name: 'Dark Azure', hex: '#078BC9', hover: '#066FA1', dark: '#033F5A', contrast: 'white' },
	{ id: 'medium-azure', name: 'Medium Azure', hex: '#36AEBF', hover: '#2B8B99', dark: '#184E56', contrast: 'black' },
	{ id: 'royal-blue', name: 'Royal Blue', hex: '#4C61DB', hover: '#3D4EAF', dark: '#222C63', contrast: 'white' },

	// ── Teals & greens ───────────────────────────────────────────────────────
	{ id: 'dark-turquoise', name: 'Dark Turquoise', hex: '#008F9B', hover: '#00727C', dark: '#004046', contrast: 'white' },
	{ id: 'green', name: 'Green', hex: '#237841', hover: '#1C6034', dark: '#10361D', contrast: 'white' },
	{ id: 'dark-green', name: 'Dark Green', hex: '#184632', hover: '#133828', dark: '#0B2016', contrast: 'white' },
	{ id: 'bright-green', name: 'Bright Green', hex: '#4B9F4A', hover: '#3C7F3B', dark: '#224821', contrast: 'white' },
	{ id: 'lime', name: 'Lime', hex: '#BBE90B', hover: '#96BA09', dark: '#546905', contrast: 'black' },
	{ id: 'olive-green', name: 'Olive Green', hex: '#9B9A5A', hover: '#7C7B48', dark: '#464528', contrast: 'black' },
	{ id: 'sand-green', name: 'Sand Green', hex: '#A0BCAC', hover: '#80968A', dark: '#48554D', contrast: 'black' },

	// ── Yellows & oranges ────────────────────────────────────────────────────
	{ id: 'yellow', name: 'Yellow', hex: '#F2CD37', hover: '#C2A42C', dark: '#6D5C19', contrast: 'black' },
	{ id: 'bright-light-orange', name: 'Bright Light Orange', hex: '#F8BB3D', hover: '#C69631', dark: '#70541B', contrast: 'black' },
	{ id: 'orange', name: 'Orange', hex: '#FE8A18', hover: '#CB6E13', dark: '#723E0B', contrast: 'black' },
	{ id: 'medium-orange', name: 'Medium Orange', hex: '#FFA70B', hover: '#CC8609', dark: '#734B05', contrast: 'black' },
	{ id: 'earth-orange', name: 'Earth Orange', hex: '#FA9C1C', hover: '#C87D16', dark: '#70460D', contrast: 'black' },
	{ id: 'dark-orange', name: 'Dark Orange', hex: '#A95500', hover: '#874400', dark: '#4C2600', contrast: 'white' },

	// ── Browns & tans ────────────────────────────────────────────────────────
	{ id: 'nougat', name: 'Nougat', hex: '#D09168', hover: '#A67453', dark: '#5E412F', contrast: 'black' },
	{ id: 'medium-nougat', name: 'Medium Nougat', hex: '#AA7D55', hover: '#886444', dark: '#4C3826', contrast: 'white' },
	{ id: 'dark-tan', name: 'Dark Tan', hex: '#958A73', hover: '#776E5C', dark: '#433E34', contrast: 'white' },
	{ id: 'reddish-brown', name: 'Reddish Brown', hex: '#582A12', hover: '#46220E', dark: '#281308', contrast: 'white' },
	{ id: 'brown', name: 'Brown', hex: '#583927', hover: '#462E1F', dark: '#281A12', contrast: 'white' },
	{ id: 'dark-brown', name: 'Dark Brown', hex: '#352100', hover: '#2A1A00', dark: '#180F00', contrast: 'white' },

	// ── Neutrals ─────────────────────────────────────────────────────────────
	{ id: 'dark-bluish-gray', name: 'Dark Bluish Gray', hex: '#6C6E68', hover: '#565853', dark: '#31322F', contrast: 'white' },
	{ id: 'black', name: 'Black', hex: '#05131D', hover: '#040F17', dark: '#02090D', contrast: 'white' }
];

export function getLegoColor(id: string | null | undefined): LegoColor {
	if (typeof id === 'string') {
		const found = LEGO_COLORS.find((color) => color.id === id);
		if (found) return found;
	}
	return LEGO_COLORS.find((color) => color.id === DEFAULT_COLOR_ID)!;
}

/**
 * Apply a color's CSS variables to a target element (defaults to :root).
 * Idempotent and side-effect-free except for the four custom properties.
 */
export function applyLegoColorVars(color: LegoColor, target: HTMLElement | null = null): void {
	if (typeof document === 'undefined') return;
	const el = target ?? document.documentElement;
	el.style.setProperty('--color-primary', color.hex);
	el.style.setProperty('--color-primary-hover', color.hover);
	el.style.setProperty('--color-primary-dark', color.dark);
	el.style.setProperty('--color-primary-contrast', color.contrast === 'white' ? '#ffffff' : '#000000');
}
