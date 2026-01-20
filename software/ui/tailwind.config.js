/** @type {import('tailwindcss').Config} */
export default {
	content: ['./src/**/*.{html,js,svelte,ts}'],
	darkMode: 'class',
	theme: {
		extend: {
			colors: {
				bg: {
					DEFAULT: '#ffffff',
					dark: '#0a0a0a'
				},
				surface: {
					DEFAULT: '#f5f5f5',
					dark: '#171717'
				},
				border: {
					DEFAULT: '#e5e5e5',
					dark: '#262626'
				},
				text: {
					DEFAULT: '#171717',
					dark: '#fafafa',
					muted: '#737373',
					'muted-dark': '#a3a3a3'
				}
			}
		}
	},
	plugins: []
};
