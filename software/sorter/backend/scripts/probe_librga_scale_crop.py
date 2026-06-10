#!/usr/bin/env python3
"""Probe direct librga scale/crop for the camera media pipeline.

This is intentionally separate from the GStreamer graph. The current Orange Pi
image has no standalone GStreamer RGA transform element, while librga itself can
still be used from process code. A green result here means a follow-up runtime
can replace CPU scaling for YOLO/preview staging by mapping NV12 appsink frames
and asking RGA to resize/crop them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_TIMEOUT_S = 8.0

PROBE_C_SOURCE = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <rga/im2d.h>
#include <rga/rga.h>

static void fill_nv12(uint8_t *buf, int w, int h) {
    size_t y_size = (size_t)w * (size_t)h;
    for (size_t i = 0; i < y_size; ++i) {
        buf[i] = (uint8_t)(16 + (i % 220));
    }
    for (size_t i = y_size; i < y_size + y_size / 2; i += 2) {
        buf[i] = 128;
        if (i + 1 < y_size + y_size / 2) {
            buf[i + 1] = 128;
        }
    }
}

static int ok_status(IM_STATUS status) {
    return status == IM_STATUS_NOERROR || status == IM_STATUS_SUCCESS;
}

static int run_case(
    const char *name,
    int src_width,
    int src_height,
    int dst_width,
    int dst_height,
    int crop_x,
    int crop_y,
    int crop_width,
    int crop_height
) {
    size_t src_size = (size_t)src_width * (size_t)src_height * 3 / 2;
    size_t dst_size = (size_t)dst_width * (size_t)dst_height * 3 / 2;
    size_t crop_size = (size_t)crop_width * (size_t)crop_height * 3 / 2;
    uint8_t *src = NULL;
    uint8_t *dst = NULL;
    uint8_t *crop_dst = NULL;
    uint8_t *crop_scale_dst = NULL;

    if (posix_memalign((void **)&src, 4096, src_size) ||
        posix_memalign((void **)&dst, 4096, dst_size) ||
        posix_memalign((void **)&crop_dst, 4096, crop_size) ||
        posix_memalign((void **)&crop_scale_dst, 4096, dst_size)) {
        fprintf(stderr, "%s alloc failed\n", name);
        return 20;
    }

    fill_nv12(src, src_width, src_height);
    memset(dst, 0, dst_size);
    memset(crop_dst, 0, crop_size);
    memset(crop_scale_dst, 0, dst_size);

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
    im_handle_param_t crop_param = {
        .width = (uint32_t)crop_width,
        .height = (uint32_t)crop_height,
        .format = RK_FORMAT_YCbCr_420_SP,
    };

    rga_buffer_handle_t src_handle = importbuffer_virtualaddr(src, &src_param);
    rga_buffer_handle_t dst_handle = importbuffer_virtualaddr(dst, &dst_param);
    rga_buffer_handle_t crop_handle = importbuffer_virtualaddr(crop_dst, &crop_param);
    rga_buffer_handle_t crop_scale_handle = importbuffer_virtualaddr(crop_scale_dst, &dst_param);
    if (!src_handle || !dst_handle || !crop_handle || !crop_scale_handle) {
        fprintf(
            stderr,
            "%s importbuffer failed src=%u dst=%u crop=%u crop_scale=%u\n",
            name,
            src_handle,
            dst_handle,
            crop_handle,
            crop_scale_handle
        );
        return 21;
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
    rga_buffer_t crop_img = wrapbuffer_handle(
        crop_handle,
        crop_width,
        crop_height,
        RK_FORMAT_YCbCr_420_SP
    );
    rga_buffer_t crop_scale_img = wrapbuffer_handle(
        crop_scale_handle,
        dst_width,
        dst_height,
        RK_FORMAT_YCbCr_420_SP
    );
    rga_buffer_t pat_img;
    memset(&pat_img, 0, sizeof(pat_img));

    IM_STATUS resize_status = imresize_t(src_img, dst_img, 0, 0, INTER_LINEAR, 1);
    if (!ok_status(resize_status)) {
        fprintf(stderr, "%s imresize failed: %d %s\n", name, resize_status, imStrError(resize_status));
        return 22;
    }

    im_rect crop_rect = {crop_x, crop_y, crop_width, crop_height};
    IM_STATUS crop_status = imcrop_t(src_img, crop_img, crop_rect, 1);
    if (!ok_status(crop_status)) {
        fprintf(stderr, "%s imcrop failed: %d %s\n", name, crop_status, imStrError(crop_status));
        return 23;
    }

    im_rect src_rect = {crop_x, crop_y, crop_width, crop_height};
    im_rect dst_rect = {0, 0, dst_width, dst_height};
    im_rect pat_rect = {0, 0, 0, 0};
    IM_STATUS crop_scale_status = improcess(
        src_img,
        crop_scale_img,
        pat_img,
        src_rect,
        dst_rect,
        pat_rect,
        IM_SYNC
    );
    if (!ok_status(crop_scale_status)) {
        fprintf(
            stderr,
            "%s improcess crop-scale failed: %d %s\n",
            name,
            crop_scale_status,
            imStrError(crop_scale_status)
        );
        return 24;
    }

    unsigned long resize_sum = 0;
    unsigned long crop_sum = 0;
    unsigned long crop_scale_sum = 0;
    for (size_t i = 0; i < dst_size; ++i) {
        resize_sum += dst[i];
        crop_scale_sum += crop_scale_dst[i];
    }
    for (size_t i = 0; i < crop_size; ++i) {
        crop_sum += crop_dst[i];
    }

    printf(
        "%s resize=%d crop=%d crop_scale=%d resize_sum=%lu crop_sum=%lu crop_scale_sum=%lu\n",
        name,
        resize_status,
        crop_status,
        crop_scale_status,
        resize_sum,
        crop_sum,
        crop_scale_sum
    );

    releasebuffer_handle(src_handle);
    releasebuffer_handle(dst_handle);
    releasebuffer_handle(crop_handle);
    releasebuffer_handle(crop_scale_handle);
    free(src);
    free(dst);
    free(crop_dst);
    free(crop_scale_dst);
    return (resize_sum > 0 && crop_sum > 0 && crop_scale_sum > 0) ? 0 : 25;
}

int main(void) {
    int rc = run_case("720p_to_yolo", 1280, 720, 640, 360, 320, 180, 640, 360);
    if (rc != 0) {
        return rc;
    }
    return run_case("4k_to_yolo", 3840, 2160, 640, 360, 960, 540, 1920, 1080);
}
"""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[..., subprocess.CompletedProcess[str] | CommandResult]


def _run(
    args: list[str],
    *,
    runner: CommandRunner = subprocess.run,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    cwd: str | None = None,
) -> CommandResult:
    try:
        result = runner(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=cwd,
        )
    except Exception as exc:
        return CommandResult(returncode=127, stderr=str(exc))
    return CommandResult(
        returncode=int(getattr(result, "returncode", 127)),
        stdout=str(getattr(result, "stdout", "") or ""),
        stderr=str(getattr(result, "stderr", "") or ""),
    )


def build_probe_report(
    *,
    runner: CommandRunner = subprocess.run,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    pkg_config = shutil.which("pkg-config")
    device_node = Path("/dev/rga")
    if not cc:
        return {
            "ok": False,
            "available": False,
            "reason": "No C compiler found for the librga runtime probe.",
        }
    if not pkg_config:
        return {
            "ok": False,
            "available": False,
            "reason": "pkg-config is not available.",
        }

    pkg = _run([pkg_config, "--cflags", "--libs", "librga"], runner=runner, timeout_s=timeout_s)
    if pkg.returncode != 0:
        return {
            "ok": False,
            "available": False,
            "reason": "librga pkg-config metadata is not available.",
            "stderr": pkg.stderr.strip(),
        }

    with tempfile.TemporaryDirectory(prefix="sorter-librga-probe-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        source_path = tmp_path / "probe_librga_scale_crop.c"
        binary_path = tmp_path / "probe_librga_scale_crop"
        source_path.write_text(PROBE_C_SOURCE, encoding="utf-8")
        compile_cmd = [cc, str(source_path), *pkg.stdout.split(), "-o", str(binary_path)]
        compiled = _run(compile_cmd, runner=runner, timeout_s=timeout_s, cwd=tmp_dir)
        if compiled.returncode != 0:
            return {
                "ok": False,
                "available": True,
                "compiled": False,
                "device_node": str(device_node),
                "device_node_exists": device_node.exists(),
                "reason": "librga runtime probe did not compile.",
                "stdout": compiled.stdout.strip(),
                "stderr": compiled.stderr.strip(),
            }

        runtime = _run([str(binary_path)], runner=runner, timeout_s=timeout_s, cwd=tmp_dir)
        output = "\n".join(part for part in (runtime.stdout, runtime.stderr) if part).strip()
        ok = runtime.returncode == 0
        return {
            "ok": ok,
            "available": True,
            "compiled": True,
            "runtime_ready": ok,
            "device_node": str(device_node),
            "device_node_exists": device_node.exists(),
            "input_memory": "virtualaddr",
            "pixel_format": "NV12",
            "operations": {
                "resize": ok,
                "crop": ok,
                "crop_scale": ok,
            },
            "tested_cases": [
                {
                    "name": "720p_to_yolo",
                    "source": {"width": 1280, "height": 720},
                    "output": {"width": 640, "height": 360},
                    "crop": {"x": 320, "y": 180, "width": 640, "height": 360},
                },
                {
                    "name": "4k_to_yolo",
                    "source": {"width": 3840, "height": 2160},
                    "output": {"width": 640, "height": 360},
                    "crop": {"x": 960, "y": 540, "width": 1920, "height": 1080},
                },
            ],
            "reason": (
                "librga completed NV12 resize, crop, and crop-scale on virtual-address buffers."
                if ok
                else "librga runtime probe failed."
            ),
            "returncode": runtime.returncode,
            "output": output,
        }


def _print_text(report: dict[str, Any]) -> None:
    print("librga Scale/Crop Probe")
    print(f"  ok: {report.get('ok')}")
    print(f"  available: {report.get('available')}")
    print(f"  runtime_ready: {report.get('runtime_ready')}")
    print(f"  device_node: {report.get('device_node')} exists={report.get('device_node_exists')}")
    print(f"  input_memory: {report.get('input_memory')}")
    print(f"  pixel_format: {report.get('pixel_format')}")
    operations = report.get("operations")
    if isinstance(operations, dict):
        for key, value in operations.items():
            print(f"  {key}: {value}")
    if report.get("reason"):
        print(f"  reason: {report.get('reason')}")
    if report.get("output"):
        print()
        print(str(report["output"]).strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args(argv)

    report = build_probe_report(timeout_s=max(1.0, float(args.timeout)))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text(report)
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
