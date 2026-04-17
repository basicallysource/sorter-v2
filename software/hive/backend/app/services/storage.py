import hashlib
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import settings

ALLOWED_MAGIC = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG": "png",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _upload_base() -> Path:
    return Path(settings.UPLOAD_DIR)


def _safe_path_component(value: str, field_name: str) -> str:
    component = value.strip()
    if not component or component in {".", ".."} or "/" in component or "\\" in component:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
    return component


def save_upload_file(
    machine_id: str, session_id: str, sample_id: str, file: UploadFile, suffix: str
) -> str:
    directory = (
        _upload_base()
        / _safe_path_component(machine_id, "machine id")
        / _safe_path_component(session_id, "session id")
        / _safe_path_component(sample_id, "sample id")
    )
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{suffix}"
    dest = directory / filename
    with open(dest, "wb") as out:
        content = file.file.read()
        out.write(content)
    return str(dest.relative_to(_upload_base()))


def delete_sample_files(sample) -> None:
    if sample.image_path:
        _remove_file(sample.image_path)
    if sample.full_frame_path:
        _remove_file(sample.full_frame_path)
    if sample.overlay_path:
        _remove_file(sample.overlay_path)


def delete_machine_files(machine_id: str) -> None:
    machine_dir = _upload_base() / machine_id
    if machine_dir.exists():
        shutil.rmtree(machine_dir)


def get_file_path(stored_path: str) -> Path:
    full = (_upload_base() / stored_path).resolve()
    base = _upload_base().resolve()
    if not str(full).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not full.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return full


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
    directory = _upload_base() / "models" / model_safe / runtime_safe
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / name_safe

    hasher = hashlib.sha256()
    total = 0
    max_size = settings.MAX_MODEL_FILE_SIZE
    chunk_size = 1024 * 1024
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = file.file.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_size:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="Model file exceeds size limit")
                hasher.update(chunk)
                out.write(chunk)
    except HTTPException:
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return str(dest.relative_to(_upload_base())), hasher.hexdigest(), total


def get_model_variant_file(stored_path: str) -> Path:
    return get_file_path(stored_path)


def delete_model_files(model_id) -> None:
    model_safe = _safe_path_component(str(model_id), "model id")
    directory = _upload_base() / "models" / model_safe
    if directory.exists():
        shutil.rmtree(directory)


def _remove_file(stored_path: str) -> None:
    full = (_upload_base() / stored_path).resolve()
    base = _upload_base().resolve()
    if not str(full).startswith(str(base)):
        return
    if full.exists():
        full.unlink()
