import { navSections, site } from '$lib/server/content';

export const prerender = true;
export const trailingSlash = 'always';

export function load() {
	return {
		nav: navSections,
		site: { title: site.title, description: site.description, url: site.url }
	};
}
