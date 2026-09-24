// Every sentence the page builds from the Sorter's state.

import type { Join, Software, State } from './api';

/** Why the last join failed, in one sentence. */
export function joinFailure(join: Join): string {
	const n = join.ssid;
	switch (join.reason) {
		case 'password':
			return `Wrong password for ${n}.`;
		case 'not_found':
			return `The Sorter can't see ${n} from where it is.`;
		case 'no_address':
			return `${n} let the Sorter join but didn't give it an address.`;
		case 'timeout':
			return `${n} didn't answer in time.`;
		default:
			return `Couldn't join ${n}.`;
	}
}

/** "step 4 of 11": `done` counts finished steps, so the one running is next. */
function stepOf(sw: Software): string | null {
	if (sw.total <= 0) return null;
	return `step ${Math.min(sw.done + 1, sw.total)} of ${sw.total}`;
}

/** The install, in one line, for the screen that shows the address. Null
 *  when the network has no internet: that warning already says it. */
export function softwareLine(sw: Software, internet: boolean | null): string | null {
	const progress = "The address shows progress until it's ready.";
	switch (sw.state) {
		case 'ready':
			return 'The Sorter software is ready.';
		case 'failed':
			return "The Sorter software didn't install. The address shows what went wrong.";
		case 'installing': {
			const step = stepOf(sw);
			return `Installing the Sorter software${step ? ` (${step})` : ''}. ${progress}`;
		}
		case 'waiting':
			return internet === false ? null : `The Sorter software installs next. ${progress}`;
	}
}

/** The install, for Details. */
export function softwareDetail(sw: Software): string {
	const step = stepOf(sw);
	const what = sw.step ? `: ${sw.step}` : '';
	switch (sw.state) {
		case 'ready':
			return 'Ready';
		case 'failed':
			return `Didn't install${what}`;
		case 'installing':
			return `Installing${step ? `, ${step}` : ''}${what}`;
		case 'waiting':
			return 'Waiting for internet';
	}
}

export const cableDetail: Record<State['cable'], string> = {
	none: 'Not plugged in',
	plugged: 'Plugged in, no address yet',
	connected: 'Connected'
};

/** A time of day once the Sorter's clock is right, else how long ago by the
 *  Sorter's own clock (the phone's may not agree with it). */
export function when(at: number, state: State): string {
	if (state.clock_ok) {
		return new Date(at * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
	}
	const s = state.now - at;
	if (s < 60) return 'just now';
	const m = Math.floor(s / 60);
	return m < 60 ? `${m} min ago` : `${Math.floor(m / 60)} h ago`;
}
