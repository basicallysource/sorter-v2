/**
 * GET /api/hardware.json — the bought parts: fasteners, extrusion, electronics.
 *
 * Everything with `kind: "cots"` in the catalog, with its sourcing, stock and
 * attributes. See /api/catalog.json for the rest.
 */
import { json } from '@sveltejs/kit';
import raw from '$lib/data/catalog.generated.json';

export const prerender = true;

export const GET = () => json(raw.hardware);
