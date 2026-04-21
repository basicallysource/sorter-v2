import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, new URL('.', import.meta.url).pathname, 'PUBLIC_');
	const backendBaseUrl = env.PUBLIC_BACKEND_BASE_URL ?? 'http://localhost:8000';

	return {
		plugins: [tailwindcss(), sveltekit()],
		server: {
			hmr: { overlay: false },
			proxy: {
				'/bricklink': backendBaseUrl,
				'/health': backendBaseUrl,
				'/sorting-profile': backendBaseUrl
			}
		}
	};
});
