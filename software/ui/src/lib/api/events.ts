/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

export type CameraName = 'feeder' | 'classification_bottom' | 'classification_top';

export interface FrameData {
	camera: CameraName;
	timestamp: number;
	raw: string;
	annotated: string | null;
	result: FrameResultData | null;
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

export type SocketEvent = HeartbeatEvent | FrameEvent | IdentityEvent;
