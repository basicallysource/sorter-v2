/**
 * HTTP service for the ``/api/polygons`` endpoint.
 *
 * Two consumers share this endpoint — the zone editor (which reads, edits,
 * and writes back the full payload) and the dashboard root page (which
 * only reads to build camera-feed crops). Both used to construct the URL
 * and parse the response inline; this module is the single home for that
 * plumbing.
 *
 * What lives here:
 *
 * - **Wire-format types**. Both sides of the payload are loose
 *   ``Record<string, unknown>`` bags by design — the backend accepts
 *   forward-compatible additions, and each consumer tightens the inner
 *   shapes at its own layer (e.g. ``ArcParamsPayload`` inside
 *   ``ZoneSection``).
 * - ``loadPolygons(baseUrl?)`` — ``GET`` with graceful null-on-failure so
 *   callers can fall back to in-memory state.
 * - ``savePolygons(payload, baseUrl?)`` — ``POST`` that throws on HTTP
 *   error (the zone editor surfaces the thrown message to its status bar).
 * - ``parseSavedResolution(raw)`` — shared ``[width, height]`` tuple
 *   parser used whenever a payload's ``resolution`` field needs to be
 *   rescaled into the current canvas size.
 *
 * The heavier business logic — reconstructing arc/quad state from the
 * payload, merging in-memory edits with the existing persisted shape,
 * rescaling across canvas resolutions — stays with ``ZoneSection`` where
 * the coordinate context lives.
 */

import { backendHttpBaseUrl } from '$lib/backend';

export type PolygonChannelPayload = {
	polygons?: Record<string, unknown>;
	user_pts?: Record<string, unknown>;
	arc_params?: Record<string, unknown>;
	quad_params?: Record<string, unknown>;
	channel_angles?: Record<string, unknown>;
	section_zero_pts?: Record<string, unknown>;
	resolution?: unknown;
};

export type PolygonClassificationPayload = {
	polygons?: Record<string, unknown>;
	user_pts?: Record<string, unknown>;
	quad_params?: Record<string, unknown>;
	resolution?: unknown;
};

export type PolygonsPayload = {
	channel?: PolygonChannelPayload;
	classification?: PolygonClassificationPayload;
};

/**
 * Fetch the persisted polygons payload. Returns ``null`` on any transport
 * or HTTP-status failure so callers can silently keep their current
 * in-memory state (that is the pre-existing behavior in both consumers).
 */
export async function loadPolygons(
	baseUrl: string = backendHttpBaseUrl
): Promise<PolygonsPayload | null> {
	try {
		const res = await fetch(`${baseUrl}/api/polygons`);
		if (!res.ok) return null;
		return (await res.json()) as PolygonsPayload;
	} catch {
		return null;
	}
}

/**
 * Persist a polygons payload. Throws with the server's response body on
 * non-2xx so the caller can surface it — the zone editor routes it into
 * its ``statusMsg`` banner.
 */
export async function savePolygons(
	payload: PolygonsPayload,
	baseUrl: string = backendHttpBaseUrl
): Promise<void> {
	const res = await fetch(`${baseUrl}/api/polygons`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
	if (!res.ok) throw new Error(await res.text());
}

/**
 * Parse a payload's ``resolution`` field into a ``{ width, height }``
 * record, or ``null`` if the field is missing / malformed / non-positive.
 */
export function parseSavedResolution(
	raw: unknown
): { width: number; height: number } | null {
	if (!Array.isArray(raw) || raw.length < 2) return null;
	const width = Number(raw[0]);
	const height = Number(raw[1]);
	if (!Number.isFinite(width) || !Number.isFinite(height)) return null;
	if (width <= 0 || height <= 0) return null;
	return { width, height };
}
