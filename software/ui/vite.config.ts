import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, process.cwd(), 'PUBLIC_');
	const backendBaseUrl = env.PUBLIC_BACKEND_BASE_URL ?? 'http://localhost:8000';

	return {
		plugins: [tailwindcss(), sveltekit()],
		server: {
			proxy: {
				'/bricklink': backendBaseUrl,
				'/health': backendBaseUrl
			}
		}
	};
});
