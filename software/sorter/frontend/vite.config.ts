import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';
import { execSync } from 'child_process';

function getTailscaleHostname() {
	try {
		const output = execSync('tailscale status --json', { encoding: 'utf-8' });
		const status = JSON.parse(output);
		return status.Self?.HostName || null;
	} catch {
		return null;
	}
}

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, new URL('.', import.meta.url).pathname, ['PUBLIC_', 'SORTER_']);
	const backendBaseUrl = env.PUBLIC_BACKEND_BASE_URL ?? 'http://localhost:8000';
	const extraAllowedHosts = (env.SORTER_ALLOWED_HOSTS ?? '')
		.split(',')
		.map((h) => h.trim())
		.filter(Boolean);

	const tailscaleHostname = getTailscaleHostname();
	const allowedHosts = ['.ts.net', '.local', ...extraAllowedHosts];
	if (tailscaleHostname) {
		allowedHosts.push(tailscaleHostname);
	}

	return {
		plugins: [tailwindcss(), sveltekit()],
		server: {
			hmr: { overlay: false },
			allowedHosts,
			proxy: {
				'/bricklink': backendBaseUrl,
				'/health': backendBaseUrl,
				'/sorting-profile': backendBaseUrl
			}
		}
	};
});
