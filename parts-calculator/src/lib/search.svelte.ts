/**
 * The one search palette, as shared state.
 *
 * There is a single palette for the whole site, mounted once in the layout, so
 * anything that wants to open it — the header button, a keyboard shortcut, an
 * inline list filter offering to widen the search — talks to this store rather
 * than owning its own copy. Query and scope live here too, which is what lets a
 * list filter hand its half-typed query over when you press ⌘K.
 */
import { browser } from '$app/environment';
import type { SearchScope } from './search';

const RECENT_KEY = 'sorter-search-recent-v1';
const RECENT_MAX = 6;

class Palette {
	open = $state(false);
	query = $state('');
	scope = $state<SearchScope>('all');
	/** Keys of items opened from the palette, newest first. */
	recent = $state<string[]>([]);

	/** Open with a starting query — the header button opens empty, a list filter
	 *  hands over whatever was already typed into it. */
	show(query = '', scope: SearchScope = 'all') {
		this.query = query;
		this.scope = scope;
		this.open = true;
	}

	hide() {
		this.open = false;
	}

	load() {
		if (!browser) return;
		try {
			const raw = localStorage.getItem(RECENT_KEY);
			const list = raw ? JSON.parse(raw) : [];
			if (Array.isArray(list)) this.recent = list.filter((k) => typeof k === 'string').slice(0, RECENT_MAX);
		} catch {
			/* storage disabled — recents are a nicety, never a requirement */
		}
	}

	remember(key: string) {
		this.recent = [key, ...this.recent.filter((k) => k !== key)].slice(0, RECENT_MAX);
		if (!browser) return;
		try {
			localStorage.setItem(RECENT_KEY, JSON.stringify(this.recent));
		} catch {
			/* ignore */
		}
	}
}

export const palette = new Palette();

/** Which modifier this keyboard calls the command key. Only meaningful in a
 *  browser, so callers set it after mount rather than during prerender — the
 *  static HTML would otherwise ship one platform's shortcut to everyone. */
export function isMacKeyboard(): boolean {
	return browser && /mac|iphone|ipad|ipod/i.test(navigator.userAgent);
}

/** Is this keystroke the "open search" chord — ⌘K on a Mac, Ctrl-K elsewhere?
 *  `/` counts too, the way it does in every other search box on the web, but
 *  only when the user isn't already typing into something. */
export function isSearchChord(e: KeyboardEvent): boolean {
	if (e.key === 'k' && (e.metaKey || e.ctrlKey)) return true;
	return e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey && !isTyping(e.target);
}

/** Is the event coming from somewhere the user is entering text? */
function isTyping(target: EventTarget | null): boolean {
	const el = target as HTMLElement | null;
	if (!el?.tagName) return false;
	return (
		el.tagName === 'INPUT' ||
		el.tagName === 'TEXTAREA' ||
		el.tagName === 'SELECT' ||
		el.isContentEditable
	);
}
