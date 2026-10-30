import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { execSync } from 'node:child_process';
import { defineConfig } from 'vite';

// The commit this UI is built from. The backend reports the commit it runs; a
// page built from another one reloads itself (see MachineManager).
function uiCommit(): string | null {
	try {
		return execSync('git rev-parse HEAD', { encoding: 'utf8' }).trim() || null;
	} catch {
		return null;
	}
}

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	define: { __UI_COMMIT__: JSON.stringify(uiCommit()) },
	server: {
		hmr: { overlay: false },
		// allowedHosts: true because the Pi's Tailscale bare hostname (e.g. "sorter-dark-brown-axle-0ffbef")
		// isn't reliably known at Vite startup — Tailscale may not be up yet on a no-internet boot.
		// This is a local dev server on a private machine, so host-header checking isn't a meaningful
		// security boundary here.
		allowedHosts: true
	}
});
