import type { RequestHandler } from '@sveltejs/kit';

export const GET: RequestHandler = async ({ request }) => {
	const requestUrl = new URL(request.url);
	const host = request.headers.get('host') || requestUrl.host;
	const [hostname] = host.split(':');
	const backendUrl = `http://${hostname}:8000/health`;

	try {
		const response = await fetch(backendUrl, {
			signal: AbortSignal.timeout(2500)
		});

		if (response.ok) {
			return new Response(
				JSON.stringify({
					ok: true,
					backend: true
				}),
				{
					status: 200,
					headers: { 'Content-Type': 'application/json' }
				}
			);
		}
	} catch {
		// Backend unreachable or timed out
	}

	return new Response(
		JSON.stringify({
			ok: false,
			backend: false
		}),
		{
			status: 503,
			headers: { 'Content-Type': 'application/json' }
		}
	);
};
