/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

export type ClassificationAttemptStrategy = "combined" | "single_burst";
export type CameraName =
  | "feeder"
  | "classification_bottom"
  | "classification_top"
  | "c_channel_2"
  | "c_channel_3"
  | "carousel";
export type PieceStage = "created" | "distributing" | "distributed";
export type ClassificationStatus =
  | "pending"
  | "classifying"
  | "classified"
  | "unknown"
  | "not_found"
  | "multi_drop_fail"
  | "failed";

export interface CameraHealthData {
  cameras: {
    [k: string]: string;
  };
}
export interface CameraHealthEvent {
  tag: "camera_health";
  data: CameraHealthData;
}
export interface CamerasConfigData {
  cameras: {
    [k: string]: number | string | null;
  };
}
export interface CamerasConfigEvent {
  tag: "cameras_config";
  data: CamerasConfigData;
}
export interface ClassificationAttempt {
  strategy: ClassificationAttemptStrategy;
  n_burst: number;
  found: boolean;
  label?: string | null;
  applied?: boolean;
  part_id?: string | null;
  part_name?: string | null;
  preview_url?: string | null;
  confidence?: number | null;
  color_id?: string | null;
  color_name?: string | null;
  error?: string | null;
  duration_s?: number | null;
  image_ts?: number[];
}
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
  request_failed?: boolean;
  aborted?: boolean;
  dead?: boolean;
  part_id?: string | null;
  part_name?: string | null;
  part_category?: string | null;
  color_id?: string;
  color_name?: string;
  category_id?: string | null;
  confidence?: number | null;
  max_dimension_mm?: number | null;
  moving_avg_price?: number | null;
  piece_metadata?: {
    [k: string]: unknown;
  } | null;
  high_value_routed?: boolean;
  not_in_inventory?: boolean | null;
  too_big?: boolean;
  too_big_for_layer?: boolean;
  intended_layer_index?: number | null;
  destination_bin?: [unknown, unknown, unknown] | null;
  tracked_global_id?: number | null;
  classification_channel_zone_state?: string | null;
  classification_channel_zone_center_deg?: number | null;
  classification_channel_zone_half_width_deg?: number | null;
  classification_channel_exit_offset_deg?: number | null;
  first_carousel_seen_angle_deg?: number | null;
  thumbnail?: string | null;
  latest_captured_crop?: string | null;
  latest_captured_crop_ts?: number | null;
  top_image?: string | null;
  bottom_image?: string | null;
  drop_snapshot?: string | null;
  brickognize_preview_url?: string | null;
  brickognize_source_view?: string | null;
  brickognize_listing_id?: string | null;
  brickognize_item_rank?: number | null;
  brickognize_item_type?: string | null;
  brickognize_color_rank?: number | null;
  color_provider?: string | null;
  mold_provider?: string | null;
  recognition_image_set?: RecognitionImage[];
  classification_attempts?: ClassificationAttempt[];
  classification_strategy?: ClassificationAttemptStrategy | null;
  recognition_used_crop_ts?: number[];
  feeding_started_at?: number | null;
  carousel_detected_confirmed_at?: number | null;
  first_carousel_seen_ts?: number | null;
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
export interface RecognitionImage {
  image: string;
  source: string;
  used?: boolean;
  ts?: number | null;
  score?: number | null;
  excluded_from_result?: boolean;
  channel?: number | null;
  created_at?: number | null;
  sharpness?: number | null;
}
export interface KnownObjectEvent {
  tag: "known_object";
  data: KnownObjectData;
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
export interface RuntimeStatsData {
  payload: {
    [k: string]: unknown;
  };
}
export interface RuntimeStatsEvent {
  tag: "runtime_stats";
  data: RuntimeStatsData;
}
export interface SetProfilerEnabledData {
  enabled: boolean;
}
export interface SetProfilerEnabledEvent {
  tag: "set_profiler_enabled";
  data: SetProfilerEnabledData;
}
export interface SorterStateData {
  state: string;
  camera_layout?: string | null;
}
export interface SorterStateEvent {
  tag: "sorter_state";
  data: SorterStateData;
}
export interface SortingProfileStatusData {
  sync_state: {
    [k: string]: unknown;
  };
  local_profile: {
    [k: string]: unknown;
  };
}
export interface SortingProfileStatusEvent {
  tag: "sorting_profile_status";
  data: SortingProfileStatusData;
}
export interface SystemStatusData {
  hardware_state: string;
  hardware_error?: string | null;
  homing_step?: string | null;
  no_power_development_mode?: boolean;
}
export interface SystemStatusEvent {
  tag: "system_status";
  data: SystemStatusData;
}

export type SocketEvent = HeartbeatEvent | FrameEvent | IdentityEvent | KnownObjectEvent | CameraHealthEvent | SystemStatusEvent | SorterStateEvent | CamerasConfigEvent | SortingProfileStatusEvent | RuntimeStatsEvent;
