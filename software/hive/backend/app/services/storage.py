import hashlib
import os
import tempfile
import uuid

from fastapi import HTTPException, Response, UploadFile

from app.config import settings
from app.services.storage_backend import get_backend

ALLOWED_MAGIC = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG": "png",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _safe_path_component(value: str, field_name: str) -> str:
    component = value.strip()
    if not component or component in {".", ".."} or "/" in component or "\\" in component:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
    return component


def _join_key(*parts: str) -> str:
    return "/".join(part.strip("/") for part in parts if part)


def save_upload_file(
    machine_id: str, session_id: str, sample_id: str, file: UploadFile, suffix: str
) -> str:
    key = _join_key(
        _safe_path_component(machine_id, "machine id"),
        _safe_path_component(session_id, "session id"),
        _safe_path_component(sample_id, "sample id"),
        f"{uuid.uuid4().hex}{suffix}",
    )
    file.file.seek(0)
    get_backend().write_stream(key, file.file, content_type=file.content_type)
    return key


def delete_sample_files(sample) -> None:
    backend = get_backend()
    for path in (sample.image_path, sample.full_frame_path, sample.overlay_path):
        if path:
            backend.delete(path)


def delete_machine_files(machine_id: str) -> None:
    safe_id = _safe_path_component(machine_id, "machine id")
    get_backend().delete_prefix(safe_id)


def serve_stored_file(
    stored_path: str,
    *,
    headers: dict[str, str] | None = None,
    filename: str | None = None,
    media_type: str | None = None,
) -> Response:
    return get_backend().serve(
        stored_path, headers=headers, filename=filename, media_type=media_type
    )


def validate_image(file: UploadFile) -> str:
    header = file.file.read(4)
    file.file.seek(0)

    ext = None
    for magic, extension in ALLOWED_MAGIC.items():
        if header[: len(magic)] == magic:
            ext = extension
            break

    if ext is None:
        raise HTTPException(status_code=400, detail="Invalid image format. Only JPEG and PNG are allowed.")

    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)

    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")

    return f".{ext}"


def save_model_variant(
    model_id,
    runtime: str,
    file: UploadFile,
    file_name: str,
) -> tuple[str, str, int]:
    runtime_safe = _safe_path_component(runtime, "runtime")
    if runtime_safe not in settings.ALLOWED_MODEL_RUNTIMES:
        raise HTTPException(status_code=400, detail="Unsupported runtime")
    model_safe = _safe_path_component(str(model_id), "model id")
    name_safe = _safe_path_component(file_name, "file name")

    hasher = hashlib.sha256()
    max_size = settings.MAX_MODEL_FILE_SIZE
    chunk_size = 1024 * 1024
    total = 0

    tmp = tempfile.NamedTemporaryFile(delete=False)
    try:
        try:
            while True:
                chunk = file.file.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_size:
                    raise HTTPException(status_code=413, detail="Model file exceeds size limit")
                hasher.update(chunk)
                tmp.write(chunk)
        finally:
            tmp.close()

        key = _join_key("models", model_safe, runtime_safe, name_safe)
        with open(tmp.name, "rb") as staged:
            get_backend().write_stream(key, staged, content_type="application/octet-stream")
        return key, hasher.hexdigest(), total
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def serve_model_variant(
    stored_path: str,
    *,
    filename: str,
    sha256: str,
    file_size: int,
) -> Response:
    headers = {
        "X-Model-SHA256": sha256,
        "Content-Length": str(file_size),
    }
    return serve_stored_file(
        stored_path,
        headers=headers,
        filename=filename,
        media_type="application/octet-stream",
    )


def delete_model_files(model_id) -> None:
    model_safe = _safe_path_component(str(model_id), "model id")
    get_backend().delete_prefix(_join_key("models", model_safe))


def delete_stored_file(stored_path: str) -> None:
    if not stored_path:
        return
    get_backend().delete(stored_path)
