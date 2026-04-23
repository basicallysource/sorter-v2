/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

export type CameraName = "feeder" | "classification_bottom" | "classification_top" | "c_channel_2" | "c_channel_3" | "carousel" | "classification_channel";
export type PieceStage = "created" | "distributing" | "distributed";
export type ClassificationStatus = "pending" | "classifying" | "classified" | "unknown" | "not_found" | "multi_drop_fail";

export interface FrameData {
  camera: CameraName;
  timestamp: number;
  raw: string;
  annotated: string | null;
  results: FrameResultData[];
  ghost_boxes?: [number, number, number, number][];
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
export interface CarouselMotionSampleData {
  observed_at: number;
  piece_angle_deg: number;
  carousel_angle_deg: number;
  piece_speed_deg_per_s: number;
  carousel_speed_deg_per_s: number;
  sync_ratio: number;
}
export interface KnownObjectData {
  uuid: string;
  created_at: number;
  updated_at: number;
  stage: PieceStage;
  classification_status: ClassificationStatus;
  part_id?: string | null;
  part_name?: string | null;
  part_category?: string | null;
  color_id?: string;
  color_name?: string;
  category_id?: string | null;
  confidence?: number | null;
  destination_bin?: [unknown, unknown, unknown] | null;
  tracked_global_id?: number | null;
  thumbnail?: string | null;
  top_image?: string | null;
  bottom_image?: string | null;
  drop_snapshot?: string | null;
  brickognize_preview_url?: string | null;
  brickognize_source_view?: string | null;
  recognition_used_crop_ts?: number[];
  feeding_started_at?: number | null;
  carousel_detected_confirmed_at?: number | null;
  first_carousel_seen_ts?: number | null;
  first_carousel_seen_angle_deg?: number | null;
  classification_channel_size_class?: string | null;
  classification_channel_zone_state?: string | null;
  classification_channel_zone_center_deg?: number | null;
  classification_channel_zone_half_width_deg?: number | null;
  classification_channel_soft_guard_deg?: number | null;
  classification_channel_hard_guard_deg?: number | null;
  carousel_motion_sync_ratio?: number | null;
  carousel_motion_sync_ratio_avg?: number | null;
  carousel_motion_sync_ratio_min?: number | null;
  carousel_motion_sync_ratio_max?: number | null;
  carousel_motion_piece_speed_deg_per_s?: number | null;
  carousel_motion_platter_speed_deg_per_s?: number | null;
  carousel_motion_sample_count?: number;
  carousel_motion_under_sync_sample_count?: number;
  carousel_motion_over_sync_sample_count?: number;
  carousel_motion_samples?: CarouselMotionSampleData[];
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
export interface CameraHealthData {
  cameras: Record<string, string>;
}
export interface CameraHealthEvent {
  tag: "camera_health";
  data: CameraHealthData;
}
export interface RuntimeStatsData {
  payload: Record<string, unknown>;
}
export interface RuntimeStatsEvent {
  tag: "runtime_stats";
  data: RuntimeStatsData;
}
export interface SystemStatusData {
  hardware_state: string;
  hardware_error: string | null;
  homing_step: string | null;
}
export interface SystemStatusEvent {
  tag: "system_status";
  data: SystemStatusData;
}
export interface SorterStateData {
  state: string;
  camera_layout: string | null;
}
export interface SorterStateEvent {
  tag: "sorter_state";
  data: SorterStateData;
}
export interface CamerasConfigData {
  cameras: Record<string, number | string | null>;
}
export interface CamerasConfigEvent {
  tag: "cameras_config";
  data: CamerasConfigData;
}
export interface SortingProfileStatusData {
  sync_state: Record<string, unknown>;
  local_profile: Record<string, unknown>;
}
export interface SortingProfileStatusEvent {
  tag: "sorting_profile_status";
  data: SortingProfileStatusData;
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

export type SocketEvent = HeartbeatEvent | FrameEvent | IdentityEvent | KnownObjectEvent | CameraHealthEvent | SystemStatusEvent | SorterStateEvent | CamerasConfigEvent | SortingProfileStatusEvent | RuntimeStatsEvent;
