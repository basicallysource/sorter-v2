// What only the person at the machine knows, kept in this browser per machine:
// that a motor turned the way it should, that the chute found its home, that a
// camera's zone and picture were looked at, that Hive was skipped. Everything
// the machine itself knows (a name, a board, a saved chute, a set-up door) is
// read from its setup summary instead, so another browser sees the same steps
// done.

export type SetupMarks = {
	// Motors whose direction was checked by eye, by name.
	motors?: Record<string, boolean>;
	// The kind of chute (its key) that last found its home here.
	chuteHome?: string | null;
	// Camera roles whose zone was reviewed, and whose picture was tuned.
	zones?: Record<string, boolean>;
	pictures?: Record<string, boolean>;
	hiveSkipped?: boolean;
	finished?: boolean;
};

function key(machineId: string): string {
	return `setup-marks:${machineId}`;
}

function readJson(name: string): Record<string, unknown> | null {
	const raw = window.localStorage.getItem(name);
	const parsed = raw ? JSON.parse(raw) : null;
	return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null;
}

export function loadMarks(machineId: string): SetupMarks {
	if (typeof window === 'undefined' || !machineId) return {};
	try {
		const marks = readJson(key(machineId));
		if (marks) return marks as SetupMarks;
		// What an older version of these steps kept.
		const checked = readJson(`setup-wizard-verification:${machineId}`) ?? {};
		const progress = readJson(`setup-wizard-progress:${machineId}`) ?? {};
		return {
			motors: (checked.verifiedSteppers as Record<string, boolean>) ?? {},
			zones: (checked.reviewedZones as Record<string, boolean>) ?? {},
			pictures: (checked.tunedPictures as Record<string, boolean>) ?? {},
			finished: progress.advanced === true
		};
	} catch {
		return {};
	}
}

export function saveMarks(machineId: string, marks: SetupMarks): void {
	if (typeof window === 'undefined' || !machineId) return;
	try {
		window.localStorage.setItem(key(machineId), JSON.stringify(marks));
	} catch {
		// A browser that keeps nothing only forgets these marks.
	}
}
