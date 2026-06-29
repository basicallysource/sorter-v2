import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	// Consult https://svelte.dev/docs/kit/integrations
	// for more information about preprocessors
	preprocess: vitePreprocess(),

	kit: {
		// SPA mode: emit a static fallback page so the FastAPI Station server can serve the
		// whole client app via StaticFiles on the AGX (single origin, no Node at runtime).
		adapter: adapter({ fallback: '200.html' })
	}
};

export default config;
