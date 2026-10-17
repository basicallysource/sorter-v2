"""The operator's view of the fleet: every machine, and what Hive knows about running it.

`/fleet` answers "which machines exist and how much has each sorted". Running
the fleet asks more of every row: what software it is on, what it is built
from, how hot and how full it is, which sorting profile it runs and whether
that is the version it was given, when each kind of upload last arrived, and
what it sorted on each of the last few weeks. All of it is already in Hive,
spread over a dozen tables; this puts it in one payload, keyed the way the
roster is, so a consumer answering an operator's question asks once.

**Every field is projected by name.** Hive stores more than this serves, and
the difference is deliberate rather than an oversight to fill in later:

* **No address of any kind.** Not the IP a heartbeat came from (a location),
  not `network_info` (how to open the machine on its own network), not a
  camera's stream URL (which can carry a password). This is a view of the
  fleet, not a way into it.
* **No hardware identifier.** The hardware report's `host` block (CPU serial,
  MAC addresses, hostname) and the boards' serial ports are left out: they
  identify a device to anything else it has touched and answer no question
  about the fleet.
* **No contact details.** An owner is their display name and, where they
  linked one, their Discord: the same handle the roster serves. Not an email.
* **No credentials or their fragments**, of a machine or a device.

What a device's status report says about itself (`devices`) is joined to the
machine it names through the report's own `accounts` list, which the sorter
sends only once its operator has registered it. Reports that name no live
machine here are still the fleet (a sorter running unregistered, or registered
somewhere else), so they are served too, under a pseudonym and without the
link: `unlinked_sorters`.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session, aliased, defer

from app.models.device import Device
from app.models.machine import Machine
from app.models.machine_daily_stats import MachineDailyStats
from app.models.machine_profile_assignment import MachineProfileAssignment
from app.models.machine_stats_cache import MachineStatsCache
from app.models.machine_sync_state import MachineSyncState
from app.models.sorting_profile import SortingProfile
from app.models.sorting_profile_version import SortingProfileVersion
from app.models.user import User

# A status report this recent means the sorter is up. Sorters report hourly and
# on boot, so this is one interval with room for a late one.
ONLINE_WINDOW = timedelta(minutes=75)

# Days of per-machine history served. Enough to see a week-on-week trend and
# a machine that went quiet, and small enough that the whole fleet's history
# stays one cheap read of the daily table.
DAILY_DAYS = 30

# Domain separator for an unlinked sorter's pseudonym, so its digest can never
# collide with one computed for another purpose (see public_stats._anon_label).
_SORTER_LABEL_SALT = b"hive/public/fleet-detail/sorter/v1"

# Sorts a device that has never reported below every one that has.
_NEVER = datetime.min.replace(tzinfo=timezone.utc)


def build(db: Session, roster: dict) -> dict:
    """The detail payload, built on the identified roster so the two agree.

    ``roster`` is `public_stats._roster(db)`. Every count and every machine in
    it carries over unchanged; this only adds to each row.
    """
    now = datetime.now(timezone.utc)
    # The roster's population (every machine not archived), as rows: the
    # roster serves ids as strings and the id columns want UUIDs.
    machines = {str(m.id): m for m in db.query(Machine).filter(Machine.archived_at.is_(None))}
    ids = [m.id for m in machines.values()]
    owners = _owner_names(db, [m.owner_id for m in machines.values()])
    caches = _caches(db, ids)
    daily = _daily(db, ids, now)
    profiles = _profiles(db, ids)
    uploads = _uploads(db, ids)
    linked, unlinked = _status_reports(db, set(machines))

    rows = []
    for entry in roster["machines"]:
        mid = entry["id"]
        machine = machines.get(mid)
        report = linked.get(mid)
        rows.append(
            {
                **entry,
                "description": machine.description if machine else None,
                "owner_display_name": owners.get(str(machine.owner_id)) if machine else None,
                "lifetime": _lifetime(caches.get(mid)),
                "daily": daily.get(mid, []),
                "status": _status(report, now) if report else None,
                "hardware": _hardware(machine.hardware_info if machine else None),
                "profile": profiles.get(mid),
                "last_upload_at": uploads.get(mid, {}),
            }
        )

    reports = [*linked.values(), *unlinked]
    return {
        **{k: v for k, v in roster.items() if k != "machines"},
        "generated_at": now.isoformat(),
        "online_window_minutes": int(ONLINE_WINDOW.total_seconds() // 60),
        "daily_days": DAILY_DAYS,
        "sorters_reporting": {
            "online_now": sum(1 for d in reports if _online(d, now)),
            "last_24h": sum(1 for d in reports if _seen_within(d, now, timedelta(hours=24))),
            "last_30d": sum(1 for d in reports if _seen_within(d, now, timedelta(days=30))),
            "ever": len(reports),
        },
        "machines": rows,
        "unlinked_sorters": [
            {"label": _sorter_label(d), **_status(d, now)}
            for d in sorted(unlinked, key=_last_seen, reverse=True)
        ],
    }


def _owner_names(db: Session, owner_ids: list) -> dict[str, str | None]:
    if not owner_ids:
        return {}
    return {
        str(uid): name
        for uid, name in db.query(User.id, User.display_name).filter(User.id.in_(set(owner_ids)))
    }


def _caches(db: Session, ids: list) -> dict[str, MachineStatsCache]:
    if not ids:
        return {}
    return {
        str(c.machine_id): c
        for c in db.query(MachineStatsCache).filter(MachineStatsCache.machine_id.in_(ids))
    }


def _lifetime(cache: MachineStatsCache | None) -> dict | None:
    """What the hourly stats worker last computed for the machine, beyond the
    roster's counters: the review state of its samples, its sessions, how long
    it has run and how much of that time it was sorting."""
    if cache is None:
        return None
    return {
        "computed_at": _iso(cache.computed_at),
        "classified": int(cache.classified or 0),
        "active_seconds": float(cache.active_seconds or 0.0),
        "ontime_pct": float(cache.ontime_pct or 0.0),
        "first_piece_at": _iso(cache.first_seen),
        "last_piece_at": _iso(cache.last_seen),
        "channel_crops": int(cache.channel_crops or 0),
        "upload_sessions": int(cache.total_sessions or 0),
        "set_parts_found": int(cache.parts_found or 0),
        "set_parts_needed": int(cache.parts_needed or 0),
        "samples": {
            "total": int(cache.total_samples or 0),
            "accepted": int(cache.accepted_samples or 0),
            "unreviewed": int(cache.unreviewed_samples or 0),
            "in_review": int(cache.in_review_samples or 0),
            "rejected": int(cache.rejected_samples or 0),
            "conflict": int(cache.conflict_samples or 0),
            "first_capture_at": _iso(cache.first_capture),
            "last_capture_at": _iso(cache.last_capture),
        },
    }


def _daily(db: Session, ids: list, now: datetime) -> dict[str, list[dict]]:
    """Each machine's last DAILY_DAYS UTC days, oldest first, from the stats
    worker's daily table. A day with no row is a day the machine sorted
    nothing, so it is absent rather than zero."""
    if not ids:
        return {}
    first_day = now.date() - timedelta(days=DAILY_DAYS - 1)
    out: dict[str, list[dict]] = {}
    for row in (
        db.query(MachineDailyStats)
        .filter(MachineDailyStats.machine_id.in_(ids), MachineDailyStats.day >= first_day)
        .order_by(MachineDailyStats.machine_id, MachineDailyStats.day)
    ):
        out.setdefault(str(row.machine_id), []).append(
            {
                "day": row.day.isoformat(),
                "pieces_seen": int(row.pieces_seen or 0),
                "distributed": int(row.distributed or 0),
                "active_seconds": float(row.active_seconds or 0.0),
            }
        )
    return out


def _profiles(db: Session, ids: list) -> dict[str, dict]:
    """The sorting profile each machine was given, and whether it runs it.

    `desired_version` is what the owner applied; `active_version` is what the
    machine last said it activated. They differ while a new version is on its
    way, and stay different when the machine cannot apply it, which is what
    `last_error` is for."""
    if not ids:
        return {}
    active = aliased(SortingProfileVersion)
    desired = aliased(SortingProfileVersion)
    rows = (
        db.query(
            MachineProfileAssignment,
            SortingProfile.name,
            active.version_number,
            desired.version_number,
        )
        .join(SortingProfile, SortingProfile.id == MachineProfileAssignment.profile_id)
        .outerjoin(active, active.id == MachineProfileAssignment.active_version_id)
        .outerjoin(desired, desired.id == MachineProfileAssignment.desired_version_id)
        .filter(MachineProfileAssignment.machine_id.in_(ids))
    )
    return {
        str(a.machine_id): {
            "name": name,
            "active_version": active_number,
            "desired_version": desired_number,
            "up_to_date": desired_number is None or active_number == desired_number,
            "last_error": a.last_error,
            "last_synced_at": _iso(a.last_synced_at),
            "last_activated_at": _iso(a.last_activated_at),
        }
        for a, name, active_number, desired_number in rows
    }


def _uploads(db: Session, ids: list) -> dict[str, dict[str, str | None]]:
    """When Hive last accepted each kind of data from each machine. A machine
    that is sorting but whose piece records stopped arriving is a sync problem,
    and this is the table that shows one."""
    if not ids:
        return {}
    out: dict[str, dict[str, str | None]] = {}
    for row in db.query(MachineSyncState).filter(MachineSyncState.machine_id.in_(ids)):
        out.setdefault(str(row.machine_id), {})[row.data_type] = _iso(row.updated_at)
    return out


def _status_reports(db: Session, live_ids: set[str]) -> tuple[dict[str, Device], list[Device]]:
    """Every device's last status report, split by whether it names a live
    machine here.

    A sorter names its machine in the report's `accounts` list. Several devices
    can name the same machine (a re-flashed card enrolls again), so a machine
    gets its most recent report and the older ones are dropped, not listed as
    sorters of their own."""
    linked: dict[str, Device] = {}
    unlinked: list[Device] = []
    devices = db.query(Device).options(defer(Device.last_ping_payload), defer(Device.hardware_info))
    for device in devices:
        names = {
            str(account.get("machine_id"))
            for account in (device.accounts or [])
            if isinstance(account, dict) and account.get("machine_id")
        } & live_ids
        if not names:
            unlinked.append(device)
            continue
        for mid in names:
            if mid not in linked or _last_seen(device) > _last_seen(linked[mid]):
                linked[mid] = device
    return linked, unlinked


def _status(device: Device, now: datetime) -> dict:
    """A device's last status report: what it runs, what it is, how it is."""
    return {
        "reported_at": _iso(device.last_seen_at),
        "online": _online(device, now),
        "first_report_at": _iso(device.first_ping_at),
        "report_count": int(device.ping_count or 0),
        "last_report_reason": device.last_ping_reason,
        "registered": device.registered,
        "software": {"version": device.software_version, "channel": device.channel, "commit": device.commit},
        "os": {"name": device.os_name, "sorter_os_version": device.sorter_os_version},
        "hardware": {
            "model": device.hw_model,
            "ram_bytes": device.ram_bytes,
            "cpu_temp_c": device.cpu_temp_c,
            "disk_free_bytes": device.disk_free_bytes,
            "disk_total_bytes": device.disk_total_bytes,
        },
        "config": {
            "machine_setup": device.machine_setup,
            "feeder_mode": device.feeder_mode,
            "classification_channel_mode": device.classification_channel_mode,
        },
        "usage": {
            "pieces_seen": device.pieces_seen,
            "pieces_classified": device.pieces_classified,
            "pieces_distributed": device.pieces_distributed,
            "seconds_powered": device.seconds_powered,
            "seconds_sorted": device.seconds_sorted,
            "best_hour_ppm": device.best_hour_ppm,
        },
        "uptime": {"process_s": device.process_uptime_s, "system_s": device.system_uptime_s},
    }


def _hardware(info: Any) -> dict | None:
    """The machine's last hardware report, by name: platform, software, the
    cameras and the controller boards. See the module docstring for what is
    left out and why."""
    if not isinstance(info, dict):
        return None
    cameras = info.get("cameras") if isinstance(info.get("cameras"), dict) else {}
    boards = info.get("controller_boards") if isinstance(info.get("controller_boards"), dict) else {}
    return {
        "captured_at": info.get("captured_at"),
        "booted_at": info.get("booted_at"),
        "platform": _pick(info.get("platform"), "model", "arch", "os", "python"),
        "software": _pick(info.get("software"), "version", "channel", "commit"),
        "system": _pick(info.get("system"), "cpu_count", "ram_bytes", "disk_total_bytes"),
        "config": _pick(info.get("config"), "machine_setup", "feeder_mode", "classification_channel_mode"),
        "cameras": [
            {
                "role": role,
                **_pick(camera, "model", "width", "height", "fps", "fourcc"),
                "calibrated": bool(camera.get("calibration")) if isinstance(camera, dict) else False,
            }
            for role, camera in cameras.items()
        ],
        "controller_boards": [_pick(board, "role", "family", "device_name") for board in boards.values()],
    }


def _pick(value: Any, *keys: str) -> dict:
    if not isinstance(value, dict):
        return {}
    return {k: value.get(k) for k in keys}


def _sorter_label(device: Device) -> str:
    """A stable opaque handle for an unlinked sorter, so a follow-up question
    can name the same one without the device's own id travelling."""
    return "s-" + hashlib.sha256(_SORTER_LABEL_SALT + str(device.id).encode()).hexdigest()[:6]


def _last_seen(device: Device) -> datetime:
    return _aware(device.last_seen_at) or _NEVER


def _online(device: Device, now: datetime) -> bool:
    return _seen_within(device, now, ONLINE_WINDOW)


def _seen_within(device: Device, now: datetime, window: timedelta) -> bool:
    seen = _aware(device.last_seen_at)
    return seen is not None and now - seen <= window


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes for timezone-aware columns."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value is not None else None
