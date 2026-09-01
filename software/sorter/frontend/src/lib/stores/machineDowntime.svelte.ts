/**
 * Flag for "the machine is down because we asked it to be".
 *
 * A full reboot or power down takes the backend away for minutes, which the
 * connection guard would otherwise report as an outage and offer to fix by
 * restarting the backend. The action that took the machine down owns the
 * user-facing progress modal, so the guard stays quiet while this is set.
 */

let deliberate = $state(false);

export const machineDowntime = {
	get deliberate() {
		return deliberate;
	},
	begin() {
		deliberate = true;
	},
	end() {
		deliberate = false;
	}
};
