// Copying a URL to the clipboard, shared by every "Share" button.

/** Prefer the async Clipboard API; fall back to the legacy execCommand path when
 *  it's unavailable or blocked (older browsers, insecure contexts) so the button
 *  still copies rather than silently doing nothing. Returns whether it worked. */
export async function copyText(text: string): Promise<boolean> {
	try {
		if (navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(text);
			return true;
		}
	} catch {
		/* fall through to the legacy path */
	}
	try {
		const ta = document.createElement('textarea');
		ta.value = text;
		ta.style.position = 'fixed';
		ta.style.opacity = '0';
		document.body.appendChild(ta);
		ta.select();
		const ok = document.execCommand('copy');
		ta.remove();
		return ok;
	} catch {
		return false;
	}
}
