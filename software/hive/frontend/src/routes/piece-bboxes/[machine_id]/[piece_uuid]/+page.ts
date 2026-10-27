import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

// A piece opens in the Piece samples page's labeling pane, beside the list it
// steps through. This older address goes there.
export const load: PageLoad = ({ params }) => {
	const sp = new URLSearchParams({ pm: params.machine_id, pu: params.piece_uuid });
	redirect(307, `/piece-bboxes?${sp.toString()}`);
};
