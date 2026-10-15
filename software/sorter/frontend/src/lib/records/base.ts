import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
import { getMachineContext } from '$lib/machines/context';

// The address of the machine whose records a Records view shows: the selected
// machine's, else the one that served the page. Call it while the component is
// set up; the function it returns can be called any time.
export function recordsBase(): () => string {
	const ctx = getMachineContext();
	return () => machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();
}
