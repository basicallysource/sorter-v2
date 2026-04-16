export type WizardStepConfirmation<Id extends string = string> = Partial<Record<Id, boolean>>;

export type PersistedVerificationState = {
	reviewedZones?: Record<string, boolean>;
	tunedPictures?: Record<string, boolean>;
	verifiedSteppers?: Record<string, boolean>;
};

export function progressStorageKey(machineId: string): string {
	return `setup-wizard-progress:${machineId}`;
}

export function verificationStorageKey(machineId: string): string {
	return `setup-wizard-verification:${machineId}`;
}

export function loadStoredConfirmations<Id extends string>(
	machineId: string
): WizardStepConfirmation<Id> {
	if (typeof window === 'undefined' || !machineId) return {};
	try {
		const raw = window.localStorage.getItem(progressStorageKey(machineId));
		if (!raw) return {};
		const parsed = JSON.parse(raw);
		return parsed && typeof parsed === 'object' ? (parsed as WizardStepConfirmation<Id>) : {};
	} catch {
		return {};
	}
}

export function persistConfirmations<Id extends string>(
	machineId: string,
	confirmations: WizardStepConfirmation<Id>
): void {
	if (typeof window === 'undefined' || !machineId) return;
	try {
		window.localStorage.setItem(progressStorageKey(machineId), JSON.stringify(confirmations));
	} catch {
		// ignore storage issues
	}
}

export function loadStoredVerificationState(machineId: string): {
	reviewedZones: Record<string, boolean>;
	tunedPictures: Record<string, boolean>;
	verifiedSteppers: Record<string, boolean>;
} {
	const empty = { reviewedZones: {}, tunedPictures: {}, verifiedSteppers: {} };
	if (typeof window === 'undefined' || !machineId) return empty;
	try {
		const raw = window.localStorage.getItem(verificationStorageKey(machineId));
		if (!raw) return empty;
		const parsed = JSON.parse(raw) as PersistedVerificationState | null;
		return {
			reviewedZones:
				parsed?.reviewedZones && typeof parsed.reviewedZones === 'object'
					? parsed.reviewedZones
					: {},
			tunedPictures:
				parsed?.tunedPictures && typeof parsed.tunedPictures === 'object'
					? parsed.tunedPictures
					: {},
			verifiedSteppers:
				parsed?.verifiedSteppers && typeof parsed.verifiedSteppers === 'object'
					? parsed.verifiedSteppers
					: {}
		};
	} catch {
		return empty;
	}
}

export function persistVerificationState(
	machineId: string,
	state: PersistedVerificationState
): void {
	if (typeof window === 'undefined' || !machineId) return;
	try {
		window.localStorage.setItem(verificationStorageKey(machineId), JSON.stringify(state));
	} catch {
		// ignore storage issues
	}
}
