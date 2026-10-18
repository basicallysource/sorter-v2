// The page scrolls inside the app's frame on a wide screen and in the window on
// a phone (AppShell). This finds what scrolls for an element on the page.
export function scrollerOf(el: HTMLElement | null): HTMLElement | null {
	for (let up = el?.parentElement ?? null; up; up = up.parentElement) {
		const overflow = getComputedStyle(up).overflowY;
		if ((overflow === 'auto' || overflow === 'scroll') && up.scrollHeight > up.clientHeight) {
			return up;
		}
	}
	return document.scrollingElement as HTMLElement | null;
}
