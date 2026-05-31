import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		port: 5176,
		proxy: {
			// During `pnpm dev` proxy API calls to the local mock backend.
			'/api': 'http://localhost:8088',
			'/hotspot-detect.html': 'http://localhost:8088',
			'/generate_204': 'http://localhost:8088',
			'/gen_204': 'http://localhost:8088',
			'/connecttest.txt': 'http://localhost:8088',
			'/ncsi.txt': 'http://localhost:8088',
			'/canonical.html': 'http://localhost:8088'
		}
	}
});
