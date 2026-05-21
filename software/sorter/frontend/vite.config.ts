import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, new URL('.', import.meta.url).pathname, ['PUBLIC_', 'SORTER_']);
	const backendBaseUrl = env.PUBLIC_BACKEND_BASE_URL ?? 'http://localhost:8000';
	const extraAllowedHosts = (env.SORTER_ALLOWED_HOSTS ?? '')
		.split(',')
		.map((h) => h.trim())
		.filter(Boolean);

	return {
		plugins: [tailwindcss(), sveltekit()],
		server: {
			hmr: { overlay: false },
			allowedHosts: ['.ts.net', '.local', ...extraAllowedHosts],
			proxy: {
				'/bricklink': backendBaseUrl,
				'/health': backendBaseUrl,
				'/sorting-profile': backendBaseUrl
			}
		}
	};
});
