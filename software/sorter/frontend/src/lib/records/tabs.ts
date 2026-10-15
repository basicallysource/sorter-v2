// The views of the Records page. One list feeds both places that show them:
// the page's tabs (src/routes/records/+layout.svelte) and the Records item's
// menu in the top bar (AppHeader). Each view has an address of its own.
export type RecordsView = 'overview' | 'runs' | 'pieces' | 'incidents';

export const recordsViews: { value: RecordsView; label: string; href: string }[] = [
	{ value: 'overview', label: 'Overview', href: '/records' },
	{ value: 'runs', label: 'Runs', href: '/records/runs' },
	{ value: 'pieces', label: 'Pieces', href: '/records/pieces' },
	{ value: 'incidents', label: 'Incidents', href: '/records/incidents' }
];

// The view an address is on; the overview is the page's own address.
export function recordsViewAt(pathname: string): RecordsView {
	const path = pathname.replace(/\/+$/, '');
	return (
		recordsViews.find((v) => v.href !== '/records' && path.startsWith(v.href))?.value ?? 'overview'
	);
}
