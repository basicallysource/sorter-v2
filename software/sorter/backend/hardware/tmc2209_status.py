"""Small helpers for TMC2209 driver status words."""

from __future__ import annotations

from typing import Any

TMC_REG_DRV_STATUS = 0x6F


def parse_drv_status(raw: int) -> dict[str, Any]:
    """Decode the TMC2209 DRV_STATUS register into operator-facing flags."""

    return {
        "ot": bool(raw & (1 << 1)),
        "otpw": bool(raw & (1 << 0)),
        "s2ga": bool(raw & (1 << 2)),
        "s2gb": bool(raw & (1 << 3)),
        "ola": bool(raw & (1 << 4)),
        "olb": bool(raw & (1 << 5)),
        "stst": bool(raw & (1 << 31)),
        "stealth": bool(raw & (1 << 30)),
        "cs_actual": (raw >> 16) & 0x1F,
        "sg_result": (raw >> 10) & 0x3FF,
        "t120": bool(raw & (1 << 8)),
        "t143": bool(raw & (1 << 7)),
        "t150": bool(raw & (1 << 6)),
        "t157": bool(raw & (1 << 11)),
    }


def active_temperature_flags(status: dict[str, Any]) -> list[str]:
    return [
        flag
        for flag in ("ot", "otpw", "t157", "t150", "t143", "t120")
        if bool(status.get(flag))
    ]


def overtemperature_fault_flags(
    status: dict[str, Any],
    *,
    include_prewarn: bool = True,
) -> list[str]:
    flags: list[str] = []
    if bool(status.get("ot")):
        flags.append("ot")
    if include_prewarn and bool(status.get("otpw")):
        flags.append("otpw")
    return flags
