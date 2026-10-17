import { scrollerOf } from './scroll';

// A Svelte action: tell when an element comes near the screen and when it
// leaves, within `margin` pixels of what scrolls around it (the app's frame on
// a wide screen, the window on a phone). A long list uses it so that only the
// rows near the reader load their pictures.
export function near(
	node: HTMLElement,
	handlers: { enter: () => void; leave: () => void; margin?: number }
) {
	let current = handlers;
	const scroller = scrollerOf(node);
	const observer = new IntersectionObserver(
		(entries) => {
			// The last entry is the latest state of the element.
			const last = entries[entries.length - 1];
			if (last.isIntersecting) current.enter();
			else current.leave();
		},
		{
			root: scroller === document.scrollingElement ? null : scroller,
			rootMargin: `${current.margin ?? 800}px 0px`
		}
	);
	observer.observe(node);
	return {
		update(next: typeof handlers) {
			current = next;
		},
		destroy() {
			observer.disconnect();
			current.leave();
		}
	};
}
