import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		proxy: {
			'/api': 'http://localhost:8002'
		}
	},
	// lucide-svelte ships uncompiled .svelte icon files; keep it in Vite's SSR
	// pipeline so they're compiled rather than handed to Node's ESM loader.
	ssr: {
		noExternal: ['lucide-svelte']
	}
});
