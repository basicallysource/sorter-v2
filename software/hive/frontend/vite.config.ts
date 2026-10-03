import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		// Reachable over Tailscale so the dev Hive can be used like a hosted
		// instance (browse at http://<machine>.<tailnet>.ts.net:5174).
		host: true,
		allowedHosts: ['.ts.net'],
		proxy: {
			'/api': 'http://localhost:8002'
		}
	}
});
