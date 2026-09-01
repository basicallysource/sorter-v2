import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter(),
		prerender: {
			// Content is hand-written markdown; a broken internal link should
			// warn, not kill the build.
			handleHttpError: 'warn',
			handleMissingId: 'warn'
		}
	}
};

export default config;
