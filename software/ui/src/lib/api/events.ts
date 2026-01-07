/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

export interface HeartbeatData {
  timestamp: number;
}
export interface HeartbeatEvent {
  tag: "heartbeat";
  data: HeartbeatData;
}

export type SocketEvent = HeartbeatEvent;


