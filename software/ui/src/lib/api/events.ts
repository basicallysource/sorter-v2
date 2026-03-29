/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

export type CameraName = "feeder" | "classification_bottom" | "classification_top" | "c_channel_2" | "c_channel_3" | "carousel";
export type PieceStage = "created" | "distributing" | "distributed";
export type ClassificationStatus = "pending" | "classifying" | "classified" | "unknown" | "not_found" | "multi_drop_fail";

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
  tag: "frame";
  data: FrameData;
}
export interface HeartbeatData {
  timestamp: number;
}
export interface HeartbeatEvent {
  tag: "heartbeat";
  data: HeartbeatData;
}
export interface IdentityEvent {
  tag: "identity";
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
  stage: PieceStage;
  classification_status: ClassificationStatus;
  part_id?: string | null;
  color_id?: string;
  color_name?: string;
  category_id?: string | null;
  confidence?: number | null;
  destination_bin?: [unknown, unknown, unknown] | null;
  thumbnail?: string | null;
  top_image?: string | null;
  bottom_image?: string | null;
  brickognize_preview_url?: string | null;
  brickognize_source_view?: string | null;
  feeding_started_at?: number | null;
  carousel_detected_confirmed_at?: number | null;
  carousel_rotate_started_at?: number | null;
  carousel_rotated_at?: number | null;
  carousel_snapping_started_at?: number | null;
  carousel_snapping_completed_at?: number | null;
  carousel_next_baseline_captured_at?: number | null;
  carousel_next_ready_at?: number | null;
  classified_at?: number | null;
  distributing_at?: number | null;
  distribution_target_selected_at?: number | null;
  distribution_motion_started_at?: number | null;
  distribution_positioned_at?: number | null;
  distributed_at?: number | null;
}
export interface KnownObjectEvent {
  tag: "known_object";
  data: KnownObjectData;
}
export interface RuntimeStatsData {
  payload: Record<string, unknown>;
}
export interface RuntimeStatsEvent {
  tag: "runtime_stats";
  data: RuntimeStatsData;
}
export interface PauseCommandData {}
export interface PauseCommandEvent {
  tag: "pause";
  data: PauseCommandData;
}
export interface ResumeCommandData {}
export interface ResumeCommandEvent {
  tag: "resume";
  data: ResumeCommandData;
}

export type SocketEvent = HeartbeatEvent | FrameEvent | IdentityEvent | KnownObjectEvent | RuntimeStatsEvent;
