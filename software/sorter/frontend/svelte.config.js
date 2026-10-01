import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),

	kit: {
		// The UI is static files in build/, which the backend's supervisor
		// serves. Every path without a file gets index.html, the app shell, and
		// the app renders in the browser (ssr is off in src/routes/+layout.ts).
		adapter: adapter({ fallback: 'index.html', precompress: true })
	}
};

export default config;
