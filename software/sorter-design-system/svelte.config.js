import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// Static files, like the Sorter UI: every page renders in the browser
		// (ssr is off in src/routes/+layout.ts), so a component behaves here
		// exactly as it will in the app it is copied into.
		adapter: adapter({ fallback: 'index.html' })
	}
};

export default config;
