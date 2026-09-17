import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	// Outside node_modules, so the dev server works where node_modules is
	// provided read-only (an agent's environment installs it from the lockfile
	// and mounts it that way). Ignored by git.
	cacheDir: '.vite',
	server: {
		fs: {
			// content markdown + liquid includes live outside routes/lib
			allow: ['..']
		}
	}
});
