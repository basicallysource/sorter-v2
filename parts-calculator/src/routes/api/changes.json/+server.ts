/**
 * GET /api/changes.json — the tracked changes behind the /changes page.
 *
 * Small and the useful one to poll: it is what says whether a part is known
 * broken or about to be revised, so a builder can hold off printing it. Each
 * entry has a `priority`, a `description`, an optional `condition` and the
 * `targets` it applies to. See /api/catalog.json for the rest.
 */
import { json } from '@sveltejs/kit';
import raw from '$lib/data/catalog.generated.json';

export const prerender = true;

export const GET = () => json(raw.changes);
