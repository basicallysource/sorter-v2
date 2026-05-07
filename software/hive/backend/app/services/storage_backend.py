from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from app.config import settings


class StorageBackend(ABC):
    @abstractmethod
    def write_stream(self, key: str, source: BinaryIO, content_type: str | None = None) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def serve(
        self,
        key: str,
        headers: dict[str, str] | None = None,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> Response: ...


class LocalStorageBackend(StorageBackend):
    def __init__(self, base_dir: str) -> None:
        self.base = Path(base_dir)

    def _full(self, key: str) -> Path:
        return self.base / key

    def write_stream(self, key: str, source: BinaryIO, content_type: str | None = None) -> None:
        dest = self._full(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as out:
            shutil.copyfileobj(source, out)

    def delete(self, key: str) -> None:
        full = (self._full(key)).resolve()
        base = self.base.resolve()
        if not str(full).startswith(str(base)):
            return
        if full.exists():
            full.unlink()

    def delete_prefix(self, prefix: str) -> None:
        full = (self._full(prefix)).resolve()
        base = self.base.resolve()
        if not str(full).startswith(str(base)):
            return
        if full.exists():
            shutil.rmtree(full)

    def exists(self, key: str) -> bool:
        return self._full(key).exists()

    def serve(
        self,
        key: str,
        headers: dict[str, str] | None = None,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> Response:
        full = self._full(key).resolve()
        base = self.base.resolve()
        if not str(full).startswith(str(base)):
            raise HTTPException(status_code=400, detail="Invalid file path")
        if not full.exists():
            raise HTTPException(status_code=404, detail="File not found")
        kwargs: dict = {"headers": headers or {}}
        if filename is not None:
            kwargs["filename"] = filename
        if media_type is not None:
            kwargs["media_type"] = media_type
        return FileResponse(full, **kwargs)


class S3StorageBackend(StorageBackend):
    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None,
        region: str | None,
        access_key_id: str,
        secret_access_key: str,
        serve_mode: str = "redirect",
        presigned_expiry: int = 3600,
    ) -> None:
        import boto3

        if not bucket:
            raise RuntimeError("S3_BUCKET must be set when STORAGE_BACKEND=s3")
        if not access_key_id or not secret_access_key:
            raise RuntimeError("S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY must be set when STORAGE_BACKEND=s3")

        self.bucket = bucket
        self.serve_mode = serve_mode
        self.presigned_expiry = presigned_expiry
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region or None,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def write_stream(self, key: str, source: BinaryIO, content_type: str | None = None) -> None:
        extra: dict = {}
        if content_type:
            extra["ContentType"] = content_type
        self.client.upload_fileobj(source, self.bucket, key, ExtraArgs=extra or None)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_prefix(self, prefix: str) -> None:
        prefix_norm = prefix.rstrip("/") + "/"
        paginator = self.client.get_paginator("list_objects_v2")
        batch: list[dict] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix_norm):
            for obj in page.get("Contents", []):
                batch.append({"Key": obj["Key"]})
                if len(batch) >= 1000:
                    self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})
                    batch = []
        if batch:
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def serve(
        self,
        key: str,
        headers: dict[str, str] | None = None,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> Response:
        if self.serve_mode == "redirect":
            params: dict = {"Bucket": self.bucket, "Key": key}
            if filename:
                params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
            if media_type:
                params["ResponseContentType"] = media_type
            url = self.client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=self.presigned_expiry,
            )
            response = RedirectResponse(url=url, status_code=307)
            for name, value in (headers or {}).items():
                response.headers[name] = value
            return response

        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey as exc:
            raise HTTPException(status_code=404, detail="File not found") from exc

        body = obj["Body"]

        def iterator():
            try:
                while True:
                    chunk = body.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                body.close()

        combined_headers: dict[str, str] = dict(headers or {})
        if "Content-Length" not in combined_headers and "ContentLength" in obj:
            combined_headers["Content-Length"] = str(obj["ContentLength"])
        if filename:
            combined_headers.setdefault("Content-Disposition", f'attachment; filename="{filename}"')
        resolved_media = media_type or obj.get("ContentType") or "application/octet-stream"
        return StreamingResponse(iterator(), media_type=resolved_media, headers=combined_headers)


_backend_instance: StorageBackend | None = None


def _build_backend() -> StorageBackend:
    kind = (settings.STORAGE_BACKEND or "local").strip().lower()
    if kind == "s3":
        return S3StorageBackend(
            bucket=settings.S3_BUCKET,
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            region=settings.S3_REGION or None,
            access_key_id=settings.S3_ACCESS_KEY_ID,
            secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            serve_mode=(settings.S3_SERVE_MODE or "redirect").strip().lower(),
            presigned_expiry=settings.S3_PRESIGNED_EXPIRY_SECONDS,
        )
    if kind == "local":
        return LocalStorageBackend(base_dir=settings.UPLOAD_DIR)
    raise RuntimeError(f"Unsupported STORAGE_BACKEND: {settings.STORAGE_BACKEND!r}")


def get_backend() -> StorageBackend:
    global _backend_instance
    if _backend_instance is None:
        _backend_instance = _build_backend()
    return _backend_instance


def reset_backend_for_tests() -> None:
    global _backend_instance
    _backend_instance = None
