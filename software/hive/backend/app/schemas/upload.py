from pydantic import BaseModel, field_validator


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
    sample_payload: dict | None = None
    extra_metadata: dict | None = None

    model_config = {"extra": "allow"}

    @field_validator("local_sample_id")
    @classmethod
    def validate_local_sample_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("local_sample_id must not be empty")
        if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
            raise ValueError("local_sample_id must be a single path segment")
        return normalized
