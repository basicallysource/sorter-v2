import { env } from '$env/dynamic/public';

// SPENCER TODO: search function to find this on the local network, shhould not hardcode the address
const fallbackHttpBaseUrl = 'http://localhost:8000';
const rawHttpBaseUrl = env.PUBLIC_BACKEND_BASE_URL ?? fallbackHttpBaseUrl;
const httpBaseUrl = rawHttpBaseUrl.replace(/\/+$/, '');

const fallbackWsBaseUrl = httpBaseUrl.startsWith('https')
	? httpBaseUrl.replace(/^https/, 'wss')
	: httpBaseUrl.replace(/^http/, 'ws');

export const backendHttpBaseUrl = httpBaseUrl;
export const backendWsBaseUrl = (env.PUBLIC_BACKEND_WS_URL ?? fallbackWsBaseUrl).replace(
	/\/+$/,
	''
);
