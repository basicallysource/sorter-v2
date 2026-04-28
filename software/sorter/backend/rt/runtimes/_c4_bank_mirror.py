from __future__ import annotations

import math
from typing import Any

from rt.contracts.tracking import Track
from rt.perception.piece_track_bank import Measurement


class C4BankMirror:
    """Keep C4's PieceTrackBank mirrored from runtime tracks and dossiers."""

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime

    def admit_track(
        self,
        *,
        piece_uuid: str,
        track: Track,
        angle_deg: float,
        now_mono: float,
    ) -> None:
        rt = self._rt
        encoder = rt._carousel_angle_rad
        a_tray = self.tray_frame_rad(math.radians(angle_deg), encoder)
        meas = Measurement(
            a_meas=a_tray,
            r_meas=float(track.radius_px or 100.0),
            score=float(track.score),
            raw_track_id=int(track.global_id) if track.global_id is not None else None,
            appearance_embedding=track.appearance_embedding,
            bbox_xyxy=track.bbox_xyxy,
            confirmed_real=bool(track.confirmed_real),
            timestamp=float(now_mono),
        )
        rt._bank.admit_with_uuid(
            piece_uuid=piece_uuid,
            measurement=meas,
            now_t=now_mono,
            encoder_rad=encoder,
        )

    @staticmethod
    def tray_frame_rad(world_angle_rad: float, encoder_rad: float) -> float:
        delta = float(world_angle_rad) - float(encoder_rad)
        return math.atan2(math.sin(delta), math.cos(delta))

    def predict(self, now_mono: float) -> None:
        rt = self._rt
        rt._bank.predict_all(t=now_mono, encoder_rad=rt._carousel_angle_rad)

    def observe_tracks(self, tracks: list[Track], now_mono: float) -> None:
        rt = self._rt
        if not tracks:
            return
        encoder = rt._carousel_angle_rad
        measurements: list[tuple[str, Measurement]] = []
        for track in tracks:
            piece_uuid = track.piece_uuid or rt._piece_uuid_for_track(track)
            if not isinstance(piece_uuid, str) or piece_uuid not in rt._pieces:
                continue
            if track.angle_rad is None:
                continue
            measurements.append(
                (
                    piece_uuid,
                    Measurement(
                        a_meas=self.tray_frame_rad(float(track.angle_rad), encoder),
                        r_meas=float(track.radius_px or 100.0),
                        score=float(track.score),
                        raw_track_id=(
                            int(track.global_id)
                            if track.global_id is not None
                            else None
                        ),
                        appearance_embedding=track.appearance_embedding,
                        bbox_xyxy=track.bbox_xyxy,
                        confirmed_real=bool(track.confirmed_real),
                        timestamp=float(now_mono),
                    ),
                )
            )
        for piece_uuid, meas in measurements:
            rt._bank.update_with_measurement(
                piece_uuid, meas, now_t=now_mono, encoder_rad=encoder
            )

    def bind_classification(self, piece_uuid: str, dossier: Any) -> None:
        rt = self._rt
        result = dossier.result
        if result is None:
            return
        rt._bank.bind_classification(
            piece_uuid,
            class_label=result.part_id,
            class_confidence=getattr(result, "confidence", None),
            identity_uncertain=False,
        )

    def finalize(self, piece_uuid: str, *, ejected: bool) -> None:
        rt = self._rt
        if ejected:
            rt._bank.mark_ejected(piece_uuid)
        rt._bank.finalize(piece_uuid)

    def singleton_for_eject(self, piece_uuid: str) -> bool:
        rt = self._rt
        chute_center = math.radians(rt._exit_angle_deg)
        chute_half = math.radians(rt._exit_trailing_safety_deg)
        return rt._bank.is_singleton_in_chute(
            piece_uuid,
            chute_center_rad=chute_center,
            chute_half_width_rad=chute_half,
            encoder_rad=rt._carousel_angle_rad,
        )


__all__ = ["C4BankMirror"]
