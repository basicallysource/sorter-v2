// Copy text to the clipboard. The async clipboard only exists on a secure
// page (https, or localhost), and Hive is also served over plain http on a
// private network, so fall back to selecting a hidden field and copying it.
// Returns whether it worked, so the caller can say so when it did not.
export async function copyText(text: string): Promise<boolean> {
	try {
		if (navigator.clipboard && window.isSecureContext) {
			await navigator.clipboard.writeText(text);
			return true;
		}
	} catch {
		/* fall through to the selection copy */
	}
	const field = document.createElement('textarea');
	field.value = text;
	field.setAttribute('readonly', '');
	field.style.position = 'fixed';
	field.style.opacity = '0';
	document.body.appendChild(field);
	field.select();
	try {
		return document.execCommand('copy');
	} catch {
		return false;
	} finally {
		document.body.removeChild(field);
	}
}
