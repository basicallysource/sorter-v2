import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		hmr: { overlay: false },
		// allowedHosts: true because the Pi's Tailscale bare hostname (e.g. "sorter-dark-brown-axle-0ffbef")
		// isn't reliably known at Vite startup — Tailscale may not be up yet on a no-internet boot.
		// This is a local dev server on a private machine, so host-header checking isn't a meaningful
		// security boundary here.
		allowedHosts: true
	}
});
