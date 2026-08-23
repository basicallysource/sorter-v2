/**
 * GET /api/parts.json — the printed parts only.
 *
 * The slice most consumers want, and the one behind "what changed since": each
 * part carries `created_at`, `updated_at` and a `versions` list with a date, a
 * message and an STL URL per revision, which is everything /updates computes
 * from. See /api/catalog.json for the rest of the catalog.
 */
import { json } from '@sveltejs/kit';
import raw from '$lib/data/catalog.generated.json';

export const prerender = true;

export const GET = () => json(raw.parts);
