// The LEGO colors an operator can pick as the primary (docs/color.md), in the
// order of the official LEGO color sheet: neutrals, tans and browns, yellows,
// oranges and reds, pinks and purples, blues, greens. Solid colors only.
// Hex values are the BrickLink / Rebrickable catalog values.

export type LegoColor = { id: string; name: string; hex: string };

export const DEFAULT_COLOR_ID = 'blue';

export const LEGO_COLORS: readonly LegoColor[] = [
	// Neutrals
	{ id: 'white', name: 'White', hex: '#ffffff' },
	{ id: 'very-light-bluish-gray', name: 'Very Light Bluish Gray', hex: '#e6e3da' },
	{ id: 'very-light-gray', name: 'Very Light Gray', hex: '#e6e3e0' },
	{ id: 'light-bluish-gray', name: 'Light Bluish Gray', hex: '#afb5c7' },
	{ id: 'light-gray', name: 'Light Gray', hex: '#9ba19d' },
	{ id: 'dark-bluish-gray', name: 'Dark Bluish Gray', hex: '#6c6e68' },
	{ id: 'dark-gray', name: 'Dark Gray', hex: '#6d6e5c' },
	{ id: 'black', name: 'Black', hex: '#05131d' },
	// Tans and browns
	{ id: 'tan', name: 'Tan', hex: '#e4cd9e' },
	{ id: 'light-nougat', name: 'Light Nougat', hex: '#f6d7b3' },
	{ id: 'nougat', name: 'Nougat', hex: '#d09168' },
	{ id: 'medium-nougat', name: 'Medium Nougat', hex: '#aa7d55' },
	{ id: 'sand-red', name: 'Sand Red', hex: '#d67572' },
	{ id: 'dark-tan', name: 'Dark Tan', hex: '#958a73' },
	{ id: 'dark-orange', name: 'Dark Orange', hex: '#a95500' },
	{ id: 'medium-brown', name: 'Medium Brown', hex: '#755945' },
	{ id: 'reddish-brown', name: 'Reddish Brown', hex: '#582a12' },
	{ id: 'brown', name: 'Brown', hex: '#583927' },
	{ id: 'dark-brown', name: 'Dark Brown', hex: '#352100' },
	// Yellows, oranges and reds
	{ id: 'light-yellow', name: 'Light Yellow', hex: '#fbe696' },
	{ id: 'bright-light-yellow', name: 'Bright Light Yellow', hex: '#fff03a' },
	{ id: 'neon-yellow', name: 'Neon Yellow', hex: '#dce000' },
	{ id: 'yellow', name: 'Yellow', hex: '#f2cd37' },
	{ id: 'very-light-orange', name: 'Very Light Orange', hex: '#f3cf9b' },
	{ id: 'light-orange', name: 'Light Orange', hex: '#f8c691' },
	{ id: 'bright-light-orange', name: 'Bright Light Orange', hex: '#f8bb3d' },
	{ id: 'medium-orange', name: 'Medium Orange', hex: '#ffa70b' },
	{ id: 'orange', name: 'Orange', hex: '#fe8a18' },
	{ id: 'earth-orange', name: 'Earth Orange', hex: '#fa9c1c' },
	{ id: 'red', name: 'Red', hex: '#c91a09' },
	{ id: 'dark-red', name: 'Dark Red', hex: '#720e0f' },
	// Pinks and purples
	{ id: 'pink', name: 'Pink', hex: '#fecccf' },
	{ id: 'bright-pink', name: 'Bright Pink', hex: '#e4adc8' },
	{ id: 'dark-pink', name: 'Dark Pink', hex: '#c870a0' },
	{ id: 'magenta', name: 'Magenta', hex: '#923978' },
	{ id: 'coral', name: 'Coral', hex: '#ff698f' },
	{ id: 'lavender', name: 'Lavender', hex: '#e1d5ed' },
	{ id: 'medium-lavender', name: 'Medium Lavender', hex: '#ac78ba' },
	{ id: 'medium-violet', name: 'Medium Violet', hex: '#9391e4' },
	{ id: 'blue-violet', name: 'Blue Violet', hex: '#4c61db' },
	{ id: 'light-purple', name: 'Light Purple', hex: '#cd6298' },
	{ id: 'purple', name: 'Purple', hex: '#81007b' },
	{ id: 'dark-purple', name: 'Dark Purple', hex: '#3f3691' },
	// Blues
	{ id: 'light-aqua', name: 'Light Aqua', hex: '#adc3c0' },
	{ id: 'aqua', name: 'Aqua', hex: '#b3d7d1' },
	{ id: 'bright-light-blue', name: 'Bright Light Blue', hex: '#9fc3e9' },
	{ id: 'medium-azure', name: 'Medium Azure', hex: '#36aebf' },
	{ id: 'maersk-blue', name: 'Maersk Blue', hex: '#3592c3' },
	{ id: 'medium-blue', name: 'Medium Blue', hex: '#5a93db' },
	{ id: 'sand-blue', name: 'Sand Blue', hex: '#6074a1' },
	{ id: 'dark-azure', name: 'Dark Azure', hex: '#078bc9' },
	{ id: 'blue', name: 'Blue', hex: '#0055bf' },
	{ id: 'dark-blue-violet', name: 'Dark Blue Violet', hex: '#2032b0' },
	{ id: 'dark-blue', name: 'Dark Blue', hex: '#0a3463' },
	// Greens
	{ id: 'yellowish-green', name: 'Yellowish Green', hex: '#dfeea5' },
	{ id: 'light-green', name: 'Light Green', hex: '#c2dab8' },
	{ id: 'lime', name: 'Lime', hex: '#bbe90b' },
	{ id: 'medium-green', name: 'Medium Green', hex: '#73dca1' },
	{ id: 'olive-green', name: 'Olive Green', hex: '#9b9a5a' },
	{ id: 'sand-green', name: 'Sand Green', hex: '#a0bcac' },
	{ id: 'bright-green', name: 'Bright Green', hex: '#4b9f4a' },
	{ id: 'dark-turquoise', name: 'Dark Turquoise', hex: '#008f9b' },
	{ id: 'green', name: 'Green', hex: '#237841' },
	{ id: 'dark-green', name: 'Dark Green', hex: '#184632' }
];

export function legoColor(id: string): LegoColor {
	return (
		LEGO_COLORS.find((c) => c.id === id) ?? LEGO_COLORS.find((c) => c.id === DEFAULT_COLOR_ID)!
	);
}
