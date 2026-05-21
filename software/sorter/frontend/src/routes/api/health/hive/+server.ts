import type { RequestHandler } from '@sveltejs/kit';

export const GET: RequestHandler = async () => {
	return new Response(
		JSON.stringify({
			ok: false,
			hive: false,
			message: 'Hive health check not yet implemented'
		}),
		{
			status: 503,
			headers: { 'Content-Type': 'application/json' }
		}
	);
};
