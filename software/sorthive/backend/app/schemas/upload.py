from pydantic import BaseModel


class UploadMetadata(BaseModel):
    source_session_id: str
    local_sample_id: str
    source_role: str | None = None
    capture_reason: str | None = None
    captured_at: str | None = None
    session_name: str | None = None
    detection_algorithm: str | None = None
    detection_bboxes: list | None = None
    detection_count: int | None = None
    detection_score: float | None = None
    extra_metadata: dict | None = None

    model_config = {"extra": "allow"}
