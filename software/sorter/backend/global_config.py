from __future__ import annotations
import os
import sys
import argparse
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING
from logger import Logger
from profiler import Profiler
from blob_manager import getMachineId

if TYPE_CHECKING:
    from run_recorder import RunRecorder
    from runtime_stats import RuntimeStatsCollector
    from lifetime_stats import LifetimeStatsTracker


class RegionProviderType(Enum):
    HANDDRAWN = "handdrawn"


class Timeouts:
    main_loop_sleep_ms: float
    heartbeat_interval_ms: float

    def __init__(self):
        from defs.consts import LOOP_TICK_MS
        self.main_loop_sleep_ms = LOOP_TICK_MS
        self.heartbeat_interval_ms = 5000


class GlobalConfig:
    logger: Logger
    debug_level: int
    timeouts: Timeouts
    sorting_profile_path: str
    local_profiles_dir: str
    should_write_camera_feeds: bool
    machine_id: str
    run_id: str
    disable_chute: bool
    disable_servos: bool
    disable_c_channels: set[int]  # {1, 2, 3, 4} — c-channel rotor steppers to suppress
    disable_carousel: bool         # carousel stepper (same physical motor as c_channel_4)
    no_power_development_mode: bool
    region_provider: RegionProviderType
    profiler: Profiler
    rotary_channel_steppers_can_operate_in_parallel: bool
    use_channel_bus: bool
    disable_video_streams: list[str]  # "feeder", "classification_bottom", "classification_top"
    run_recorder: "RunRecorder"
    runtime_stats: "RuntimeStatsCollector"
    lifetime_stats: "LifetimeStatsTracker"
    brickognize_dump_root: Optional[Path]
    classification_burst_dump_root: Optional[Path]
    classification_skew_dump_root: Optional[Path]
    log_perception_attribution: bool
    def __init__(self):
        from runtime_stats import RuntimeStatsCollector

        self.debug_level = 0
        self.should_write_camera_feeds = False
        self.brickognize_dump_root: Optional[Path] = None
        self.classification_burst_dump_root: Optional[Path] = None
        self.classification_skew_dump_root: Optional[Path] = None
        # Per-frame perception attribution log (the verbose "[perception ch=N
        # src=...] in_exit=... | section_sizes ... | bbox=(...) n_drop/n_exit_only/
        # n_precise/n_in_mask ..." line from InferenceWorker._maybe_log_attribution).
        # A frame-rate-firehose debug aid; off by default so it can't flood logs.
        self.log_perception_attribution = False
        self.disable_chute = False
        # On the restart branch we explicitly simulate the distributor: the
        # Waveshare layer-servo bus isn't reliably available, but C1-C4 must
        # still run continuously. ``disable_servos=True`` makes the
        # Positioning state machine fall through without waiting on real
        # layer-servo motion. Override with ``--disable servos`` (still
        # honored) or LEGOSORTER_DISABLE env, or flip back here once the
        # layer-servo bus is reattached.
        self.disable_servos = True
        self.disable_c_channels: set[int] = set()
        self.disable_carousel = False
        self.no_power_development_mode = False
        self.rotary_channel_steppers_can_operate_in_parallel = False
        self.use_channel_bus = False
        self.disable_video_streams = ["classification_bottom"]
        self.runtime_stats = RuntimeStatsCollector()
        # Rev04: perception service for the GO_TO_ANGLE_REV01 +
        # SIMPLE_STATE_MACHINE_REV01 mode pair. None when the mode pair is
        # not active — the legacy vision path runs in that case. Set in
        # main.py after camera startup. Not an env-toggle: the mode config
        # determines whether this is non-None.
        self.perception_service = None

        # Standalone training-image grabber. Runs regardless of machine mode;
        # set in main.py after camera startup. See sample_collector.py.
        self.sample_collector: "Any" = None


def mkTimeouts() -> Timeouts:
    timeouts = Timeouts()
    return timeouts


def mkGlobalConfig() -> GlobalConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--disable",
        action="append",
        default=[],
        help="disable subsystems (e.g., --disable chute, --disable servos)",
    )
    args = parser.parse_args()

    gc = GlobalConfig()
    gc.debug_level = int(os.getenv("DEBUG_LEVEL", "0"))
    gc.timeouts = mkTimeouts()
    # Local sorting profiles live next to local_state.sqlite in the backend
    # dir: durable across git resets (gitignored) and on the same persistent
    # filesystem the rest of the machine state already trusts. The active
    # artifact is a single file the runtime reads once into memory on reload;
    # the library dir holds every saved/uploaded profile to choose from.
    backend_dir = Path(__file__).resolve().parent
    gc.sorting_profile_path = str(backend_dir / "active_sorting_profile.json")
    gc.local_profiles_dir = str(backend_dir / "sorting_profiles")
    os.makedirs(gc.local_profiles_dir, exist_ok=True)
    gc.machine_id = getMachineId()
    gc.run_id = str(uuid.uuid4())
    # Allow env-var fallback so the launching supervisor can flip these
    # without needing to thread CLI args through to a child main.py — useful
    # in distributor-simulated configurations where the layer-servo Waveshare
    # bus isn't fully wired yet but C1-C4 should still run continuously.
    env_disable = {
        token.strip()
        for token in os.getenv("LEGOSORTER_DISABLE", "").split(",")
        if token.strip()
    }
    all_disable = set(args.disable) | env_disable
    gc.disable_chute = "chute" in all_disable
    gc.disable_servos = "servos" in all_disable
    for ch in (1, 2, 3, 4):
        if f"c_channel_{ch}" in all_disable:
            gc.disable_c_channels.add(ch)
    gc.disable_carousel = "carousel" in all_disable
    gc.no_power_development_mode = os.getenv("NO_POWER_DEVELOPMENT_MODE", "0") == "1"
    if gc.no_power_development_mode:
        gc.disable_chute = True
        gc.disable_servos = True
    gc.use_channel_bus = os.getenv("USE_CHANNEL_BUS", "0") == "1"
    gc.region_provider = RegionProviderType.HANDDRAWN

    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    if os.getenv("BRICKOGNIZE_DUMP_IMAGES", "0") == "1":
        gc.brickognize_dump_root = Path(log_dir).resolve() / "brickognize" / gc.run_id
    if os.getenv("CLASSIFICATION_BURST_DUMP_IMAGES", "0") == "1":
        gc.classification_burst_dump_root = Path(log_dir).resolve() / "classification_burst" / gc.run_id
    # Cheap-but-careful: writes 1 full 4K frame + 1 crop per capture during a
    # carousel sweep when set. JPEG quality is intentionally moderate (80) and
    # writes are guarded so the rotation hot path stays cheap. Use a temp dir
    # under software/logs/ that survives across runs by gc.run_id.
    if os.getenv("CLASSIFICATION_SKEW_DUMP_IMAGES", "0") == "1":
        gc.classification_skew_dump_root = Path(log_dir).resolve() / "classification_skew" / gc.run_id
    log_file = os.path.join(log_dir, datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log")
    gc.logger = Logger(gc.debug_level, log_file=log_file)
    # Profiler enable lives in machine_params.toml ([profiler] enabled), toggled
    # from the Performance settings page. Defaults OFF: profiling adds per-call
    # timing overhead across hot loops (notably the frontend camera feed) and
    # writes telemetry to local_state.sqlite — it's a diagnostic for comparing
    # systems, not something to leave on during normal sorting. The report
    # interval stays an env knob.
    from toml_config import getProfilerConfig
    gc.profiler = Profiler(
        enabled=bool(getProfilerConfig().get("enabled", False)),
        report_interval_s=float(os.getenv("PROFILER_REPORT_INTERVAL_S", "5")),
    )

    return gc
