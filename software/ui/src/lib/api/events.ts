/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

export type CameraName = 'feeder' | 'classification_bottom' | 'classification_top';
export type KnownObjectStatus =
	| 'created'
	| 'classifying'
	| 'classified'
	| 'unknown'
	| 'not_found'
	| 'distributing'
	| 'distributed';

export interface FrameData {
	camera: CameraName;
	timestamp: number;
	raw: string;
	annotated: string | null;
	results: FrameResultData[];
}
export interface FrameResultData {
	class_id: number | null;
	class_name: string | null;
	confidence: number;
	bbox: [unknown, unknown, unknown, unknown] | null;
}
export interface FrameEvent {
	tag: 'frame';
	data: FrameData;
}
export interface HeartbeatData {
	timestamp: number;
}
export interface HeartbeatEvent {
	tag: 'heartbeat';
	data: HeartbeatData;
}
export interface IdentityEvent {
	tag: 'identity';
	data: MachineIdentityData;
}
export interface MachineIdentityData {
	machine_id: string;
	nickname: string | null;
}
export interface KnownObjectData {
	uuid: string;
	created_at: number;
	updated_at: number;
	status: KnownObjectStatus;
	part_id?: string | null;
	category_id?: string | null;
	confidence?: number | null;
	destination_bin?: [unknown, unknown, unknown] | null;
	thumbnail?: string | null;
	top_image?: string | null;
	bottom_image?: string | null;
}
export interface KnownObjectEvent {
	tag: 'known_object';
	data: KnownObjectData;
}
export interface PauseCommandData {}
export interface PauseCommandEvent {
	tag: 'pause';
	data: PauseCommandData;
}
export interface ResumeCommandData {}
export interface ResumeCommandEvent {
	tag: 'resume';
	data: ResumeCommandData;
}

export type SocketEvent = HeartbeatEvent | FrameEvent | IdentityEvent | KnownObjectEvent;
