"""Direct librga NV12 crop/scale helper.

The GStreamer image on the Orange Pi has MPP decode/encode, but currently no
stable standalone RGA transform element in the live appsink graph. This module
keeps the next hardware step small: map the decoded NV12 appsink frame, ask
librga to crop/scale it, and return a reduced NV12 buffer for inference.
"""

from __future__ import annotations

import ctypes
import hashlib
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LIBRGA_VIRTUALADDR_PATH = "librga_virtualaddr"


class LibrgaUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class Nv12CropRect:
    x: int
    y: int
    width: int
    height: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (int(self.x), int(self.y), int(self.width), int(self.height))


_C_SOURCE = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <rga/im2d.h>
#include <rga/rga.h>

static int ok_status(IM_STATUS status) {
    return status == IM_STATUS_NOERROR || status == IM_STATUS_SUCCESS;
}

static void set_error(char *err, int err_len, const char *message) {
    if (err == NULL || err_len <= 0) {
        return;
    }
    snprintf(err, (size_t)err_len, "%s", message);
}

static void set_status_error(char *err, int err_len, const char *prefix, IM_STATUS status) {
    if (err == NULL || err_len <= 0) {
        return;
    }
    snprintf(err, (size_t)err_len, "%s: %d %s", prefix, status, imStrError(status));
}

int sorter_librga_nv12_crop_scale(
    const uint8_t *src,
    int src_width,
    int src_height,
    int crop_x,
    int crop_y,
    int crop_width,
    int crop_height,
    uint8_t *dst,
    int dst_width,
    int dst_height,
    char *err,
    int err_len
) {
    uint8_t *aligned_src = NULL;
    uint8_t *aligned_dst = NULL;
    rga_buffer_handle_t src_handle = 0;
    rga_buffer_handle_t dst_handle = 0;
    int rc = 0;

    if (src == NULL || dst == NULL) {
        set_error(err, err_len, "source and destination buffers are required");
        return 10;
    }
    if (src_width <= 0 || src_height <= 0 || dst_width <= 0 || dst_height <= 0 ||
        crop_width <= 0 || crop_height <= 0) {
        set_error(err, err_len, "all dimensions must be positive");
        return 11;
    }
    if ((src_width | src_height | dst_width | dst_height | crop_x | crop_y |
         crop_width | crop_height) & 1) {
        set_error(err, err_len, "NV12 dimensions and crop coordinates must be even");
        return 12;
    }
    if (crop_x < 0 || crop_y < 0 ||
        crop_x + crop_width > src_width ||
        crop_y + crop_height > src_height) {
        set_error(err, err_len, "crop rectangle is outside the source frame");
        return 13;
    }

    size_t src_size = (size_t)src_width * (size_t)src_height * 3 / 2;
    size_t dst_size = (size_t)dst_width * (size_t)dst_height * 3 / 2;

    if (posix_memalign((void **)&aligned_src, 4096, src_size) != 0 ||
        posix_memalign((void **)&aligned_dst, 4096, dst_size) != 0) {
        set_error(err, err_len, "aligned buffer allocation failed");
        rc = 14;
        goto cleanup;
    }
    memcpy(aligned_src, src, src_size);
    memset(aligned_dst, 0, dst_size);

    im_handle_param_t src_param = {
        .width = (uint32_t)src_width,
        .height = (uint32_t)src_height,
        .format = RK_FORMAT_YCbCr_420_SP,
    };
    im_handle_param_t dst_param = {
        .width = (uint32_t)dst_width,
        .height = (uint32_t)dst_height,
        .format = RK_FORMAT_YCbCr_420_SP,
    };

    src_handle = importbuffer_virtualaddr(aligned_src, &src_param);
    dst_handle = importbuffer_virtualaddr(aligned_dst, &dst_param);
    if (!src_handle || !dst_handle) {
        set_error(err, err_len, "importbuffer_virtualaddr failed");
        rc = 15;
        goto cleanup;
    }

    rga_buffer_t src_img = wrapbuffer_handle(
        src_handle,
        src_width,
        src_height,
        RK_FORMAT_YCbCr_420_SP
    );
    rga_buffer_t dst_img = wrapbuffer_handle(
        dst_handle,
        dst_width,
        dst_height,
        RK_FORMAT_YCbCr_420_SP
    );
    rga_buffer_t pat_img;
    memset(&pat_img, 0, sizeof(pat_img));

    im_rect src_rect = {crop_x, crop_y, crop_width, crop_height};
    im_rect dst_rect = {0, 0, dst_width, dst_height};
    im_rect pat_rect = {0, 0, 0, 0};
    IM_STATUS status = improcess(
        src_img,
        dst_img,
        pat_img,
        src_rect,
        dst_rect,
        pat_rect,
        IM_SYNC
    );
    if (!ok_status(status)) {
        set_status_error(err, err_len, "librga improcess crop-scale failed", status);
        rc = 16;
        goto cleanup;
    }

    memcpy(dst, aligned_dst, dst_size);

cleanup:
    if (src_handle) {
        releasebuffer_handle(src_handle);
    }
    if (dst_handle) {
        releasebuffer_handle(dst_handle);
    }
    if (aligned_src) {
        free(aligned_src);
    }
    if (aligned_dst) {
        free(aligned_dst);
    }
    return rc;
}
"""


_LIB_LOCK = threading.Lock()
_LIBRARY: ctypes.CDLL | None = None
_LIBRARY_ERROR: str | None = None


def _command_output(args: list[str], *, timeout_s: float = 8.0) -> str:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if result.returncode != 0:
        raise LibrgaUnavailableError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def _compile_library() -> Path:
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    pkg_config = shutil.which("pkg-config")
    if not cc:
        raise LibrgaUnavailableError("No C compiler found for the librga helper.")
    if not pkg_config:
        raise LibrgaUnavailableError("pkg-config is not available for the librga helper.")
    flags = _command_output([pkg_config, "--cflags", "--libs", "librga"]).split()
    digest = hashlib.sha256(_C_SOURCE.encode("utf-8")).hexdigest()[:16]
    output_path = Path(tempfile.gettempdir()) / f"sorter-librga-nv12-{digest}.so"
    if output_path.exists():
        return output_path
    with tempfile.TemporaryDirectory(prefix="sorter-librga-nv12-build-") as tmp_dir:
        source_path = Path(tmp_dir) / "sorter_librga_nv12.c"
        tmp_output = Path(tmp_dir) / output_path.name
        source_path.write_text(_C_SOURCE, encoding="utf-8")
        cmd = [
            cc,
            "-shared",
            "-fPIC",
            "-O2",
            str(source_path),
            *flags,
            "-o",
            str(tmp_output),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        if result.returncode != 0:
            raise LibrgaUnavailableError(
                result.stderr.strip() or result.stdout.strip() or "librga helper compile failed"
            )
        tmp_output.replace(output_path)
    return output_path


def _load_library() -> ctypes.CDLL:
    global _LIBRARY, _LIBRARY_ERROR
    with _LIB_LOCK:
        if _LIBRARY is not None:
            return _LIBRARY
        if _LIBRARY_ERROR:
            raise LibrgaUnavailableError(_LIBRARY_ERROR)
        try:
            library = ctypes.CDLL(str(_compile_library()))
            function = library.sorter_librga_nv12_crop_scale
            function.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
            ]
            function.restype = ctypes.c_int
            _LIBRARY = library
            return library
        except Exception as exc:
            _LIBRARY_ERROR = str(exc)
            raise LibrgaUnavailableError(_LIBRARY_ERROR) from exc


class DirectLibrgaNv12Scaler:
    """Scale/crop NV12 frames through librga using virtual-address buffers."""

    path = LIBRGA_VIRTUALADDR_PATH

    def __init__(self) -> None:
        self._library = _load_library()

    @classmethod
    def available(cls) -> bool:
        try:
            _load_library()
            return True
        except Exception:
            return False

    @classmethod
    def describe(cls) -> dict[str, Any]:
        try:
            _load_library()
            return {
                "available": True,
                "runtime_ready": True,
                "path": LIBRGA_VIRTUALADDR_PATH,
                "input_memory": "virtualaddr",
                "pixel_format": "NV12",
                "hardware_scale_convert": True,
                "hardware_crop": True,
                "zero_copy_dmabuf": False,
            }
        except Exception as exc:
            return {
                "available": False,
                "runtime_ready": False,
                "path": LIBRGA_VIRTUALADDR_PATH,
                "reason": str(exc),
            }

    def crop_scale(
        self,
        payload: bytes | memoryview,
        *,
        width: int,
        height: int,
        output_width: int,
        output_height: int,
        crop_rect: Nv12CropRect | tuple[int, int, int, int] | None = None,
    ) -> bytes:
        width = int(width)
        height = int(height)
        output_width = int(output_width)
        output_height = int(output_height)
        rect = (
            Nv12CropRect(0, 0, width, height)
            if crop_rect is None
            else crop_rect
            if isinstance(crop_rect, Nv12CropRect)
            else Nv12CropRect(*crop_rect)
        )
        expected = width * height * 3 // 2
        data = bytes(payload)
        if len(data) != expected:
            data = _slice_tight_nv12(data, width, height)
        output_size = output_width * output_height * 3 // 2
        output = ctypes.create_string_buffer(output_size)
        src = ctypes.create_string_buffer(data)
        err = ctypes.create_string_buffer(512)
        rc = self._library.sorter_librga_nv12_crop_scale(
            src,
            width,
            height,
            int(rect.x),
            int(rect.y),
            int(rect.width),
            int(rect.height),
            output,
            output_width,
            output_height,
            err,
            len(err),
        )
        if rc != 0:
            reason = err.value.decode("utf-8", errors="replace") or f"librga returned {rc}"
            raise LibrgaUnavailableError(reason)
        return output.raw


def _slice_tight_nv12(data: bytes, width: int, height: int) -> bytes:
    """Normalize an NV12 buffer whose height stride is padded to 16 rows.

    The Rockchip MPP JPEG decoder allocates NV12 with the vertical stride
    rounded up to 16 (e.g. 1920x1080 arrives as 1920x1088), while the caps
    still report the display height. Slice both planes tight; reject
    anything else loudly.
    """
    tight = width * height * 3 // 2
    vstride = (height + 15) // 16 * 16
    padded = width * vstride * 3 // 2
    if len(data) != padded:
        raise ValueError(
            f"NV12 input has {len(data)} bytes; expected {tight} (tight) or {padded} "
            f"(vstride {vstride})"
        )
    y_plane = data[: width * height]
    uv_offset = width * vstride
    uv_plane = data[uv_offset : uv_offset + width * height // 2]
    return y_plane + uv_plane


def create_direct_librga_nv12_scaler() -> DirectLibrgaNv12Scaler | None:
    try:
        return DirectLibrgaNv12Scaler()
    except Exception:
        return None
