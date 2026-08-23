/**
 * GET /api/catalog.json — the whole catalog, exactly as the site reads it.
 *
 * Every endpoint under /api is prerendered: the site is a static build, so
 * these are plain files on the CDN, not a running server. That means no query
 * parameters and no filtering server-side — fetch and slice it yourself. The
 * narrower endpoints beside this one exist only to save you the download.
 *
 * Bodies are the catalog's own objects, unwrapped and unrenamed, so a consumer
 * of the API and a reader of the site are looking at the same fields.
 */
import { json } from '@sveltejs/kit';
import raw from '$lib/data/catalog.generated.json';

export const prerender = true;

export const GET = () => json(raw);
