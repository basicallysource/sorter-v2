/** @type {import('tailwindcss').Config} */
export default {
	content: ['./src/**/*.{html,js,svelte,ts}'],
	darkMode: 'class',
	theme: {
		extend: {
			fontFamily: {
				sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
				mono: ['"IBM Plex Mono"', 'monospace'],
			},
		}
	},
	plugins: []
};
