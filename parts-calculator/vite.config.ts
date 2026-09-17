import tailwindcss from '@tailwindcss/vite';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	// Outside node_modules, so the dev server works where node_modules is
	// provided read-only (an agent's environment installs it from the lockfile
	// and mounts it that way). Ignored by git.
	cacheDir: '.vite',
	// Vite doesn't read PORT on its own. Honour it when set so a supervising
	// tool can assign a free port; fall back to Vite's default otherwise.
	server: process.env.PORT
		? { port: Number(process.env.PORT), strictPort: true }
		: undefined,
	plugins: [
		tailwindcss(),
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) => filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			adapter: adapter()
		})
	]
});
