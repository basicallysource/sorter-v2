import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';
import { mockApi } from './mock-api';

export default defineConfig({
	// mockApi answers /api/* from fixtures under `vite dev` and does nothing in a build.
	plugins: [tailwindcss(), mockApi(), sveltekit()],
	server: { port: 5176 }
});
