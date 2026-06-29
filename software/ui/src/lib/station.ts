// Thin client for the Station + calibration API on the AGX. Same-origin in production
// (the server serves this SPA), so paths resolve against backendHttpBaseUrl.
import { backendHttpBaseUrl } from './backend';

export type StationMode = 'idle' | 'calibrating' | 'running' | 'error';

export interface Readiness {
	cameras_assigned: boolean;
	feeder_polygons: boolean;
	classification_polygons: boolean;
	classification_baseline: boolean;
}

export interface StationState {
	mode: StationMode;
	error: string | null;
	readiness: Readiness;
	missing_to_run: string[];
}

export interface CameraInfo {
	index: number;
	name: string;
	location: string;
	working: boolean;
	excluded: boolean;
	roles: string[];
}

export interface CameraStatus {
	assigned: Record<string, number>;
	missing_required: string[];
	excluded: number[];
	roles: string[];
	required_roles: string[];
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
	const res = await fetch(`${backendHttpBaseUrl}${path}`, init);
	if (!res.ok) {
		let detail: unknown = res.statusText;
		try {
			detail = (await res.json()).detail ?? detail;
		} catch {
			/* non-json error */
		}
		throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
	}
	return res.json() as Promise<T>;
}

export const station = {
	state: () => req<StationState>('/station/state'),
	run: () => req<StationState>('/station/run', { method: 'POST' }),
	stop: () => req<StationState>('/station/stop', { method: 'POST' })
};

export const cameras = {
	begin: () => req<{ cameras: CameraInfo[]; status: CameraStatus }>('/calibration/cameras/begin', { method: 'POST' }),
	list: () => req<{ cameras: CameraInfo[]; status: CameraStatus }>('/calibration/cameras/list'),
	assign: (role: string, index: number) =>
		req<CameraStatus>(`/calibration/cameras/assign?role=${encodeURIComponent(role)}&index=${index}`, { method: 'POST' }),
	unassign: (role: string) =>
		req<CameraStatus>(`/calibration/cameras/unassign?role=${encodeURIComponent(role)}`, { method: 'POST' }),
	exclude: (index: number, excluded: boolean) =>
		req<CameraStatus>(`/calibration/cameras/exclude?index=${index}&excluded=${excluded}`, { method: 'POST' }),
	end: (save: boolean) => req<StationState>(`/calibration/cameras/end?save=${save}`, { method: 'POST' }),
	// MJPEG stream URL for an <img> tag (one camera at a time).
	streamUrl: (index: number) => `${backendHttpBaseUrl}/calibration/cameras/stream/${index}`
};

// Human labels for the readiness/step keys.
export const STEP_LABELS: Record<string, string> = {
	cameras_assigned: 'Assign cameras',
	feeder_polygons: 'Draw feeder polygons',
	classification_polygons: 'Draw classification polygons',
	classification_baseline: 'Calibrate classification baseline'
};
