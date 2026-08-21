// Central SEO / OpenGraph config. Link-preview crawlers (Slack, iMessage,
// Discord, X, Facebook) don't run JavaScript and reject relative og:image /
// canonical URLs, so everything resolves against SITE_URL — the production
// origin, baked into the prerendered HTML at build time.

export const SITE_URL = 'https://parts-calculator.basically.website';
export const SITE_NAME = 'Sorter Parts Calculator';

export const DEFAULT_DESCRIPTION =
	'Configure a Sorter V2 build and get exactly what to print and buy: ' +
	'per-colour filament quantities from real sliced weights, plus downloadable STLs.';

// No default og:image on purpose. A generic hero card gives every shared link
// the same misleading picture, so pages without a meaningful image of their own
// ship a text-only card. Only pages that pass an explicit `image` (the per-part
// pages, which carry the part's own render) get an image preview.

/** Absolutise a site-relative path; pass through an already-absolute URL. */
export function absUrl(pathOrUrl: string): string {
	if (/^https?:\/\//.test(pathOrUrl)) return pathOrUrl;
	return SITE_URL + (pathOrUrl.startsWith('/') ? '' : '/') + pathOrUrl;
}

/** "<page> — Sorter Parts Calculator", or just the site name for the home page. */
export function pageTitle(title?: string): string {
	return title && title !== SITE_NAME ? `${title} — ${SITE_NAME}` : SITE_NAME;
}
