import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class Device(Base):
    """A physical sorter as known to the main hive's hosted-services layer —
    the UNREGISTERED tier of machine identity.

    Distinct from Machine on purpose. A Machine is an account object — an
    owner's registration of their sorter on some hive, of which there can be
    many. A Device is the sorter itself, enrolled silently the first time it
    touches the main hive (status ping, color prediction, future services),
    whether or not any account exists. Device rows are admin-only and are
    never surfaced to regular users.

    The device also carries the machine's status-ping telemetry (the wide
    column block below), absorbed from the legacy anonymous ``installs``
    system: one row, last-known state, full raw ping in ``last_ping_payload``.
    ``install_id`` is the operator-facing telemetry handle — shown on the
    machine at /telemetry and accepted by the public /forget endpoint, which
    clears the telemetry columns here (and deletes any legacy installs row)
    without touching the device's service identity. Plain string, no FK.

    machine_id: set if/when the operator registers this sorter with an
    account on this hive, so device data can join account data. Signup stays
    a normal fresh flow; adoption is silent.
    """

    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Sorter-generated opaque key, persisted in the machine's local state. Lets a
    # re-enroll (lost token) find its existing row instead of minting a new
    # device and fragmenting the logged images.
    device_key = Column(String(128), nullable=False, unique=True)
    token_hash = Column(String, nullable=False)
    token_prefix = Column(String(8), nullable=False)
    hardware_info = Column(JSON_VARIANT, nullable=True)
    last_seen_ip = Column(String, nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="SET NULL"), nullable=True)
    install_id = Column(String, nullable=True)

    # --- status-ping telemetry (one row, last-known state) -------------------
    # first_ping_at / ping_count fold in the legacy installs row's history when
    # a ping first links an install_id. reported_created_at is client-claimed
    # (when the machine first generated its telemetry id), set once.
    first_ping_at = Column(DateTime(timezone=True), nullable=True)
    ping_count = Column(Integer, nullable=False, default=0)
    last_ping_reason = Column(String, nullable=True)
    reported_created_at = Column(DateTime(timezone=True), nullable=True)

    # Geo derived server-side from the connecting IP — coarse only; columns
    # filled offline from last_seen_ip.
    country = Column(String, nullable=True)
    region = Column(String, nullable=True)

    software_version = Column(String, nullable=True)
    channel = Column(String, nullable=True)
    commit = Column(String, nullable=True)
    os_name = Column(String, nullable=True)
    sorter_os_version = Column(String, nullable=True)

    hw_model = Column(String, nullable=True)
    ram_bytes = Column(BigInteger, nullable=True)
    cpu_temp_c = Column(Float, nullable=True)
    disk_free_bytes = Column(BigInteger, nullable=True)
    disk_total_bytes = Column(BigInteger, nullable=True)

    machine_setup = Column(String, nullable=True)
    feeder_mode = Column(String, nullable=True)
    classification_channel_mode = Column(String, nullable=True)

    pieces_seen = Column(BigInteger, nullable=True)
    pieces_classified = Column(BigInteger, nullable=True)
    pieces_distributed = Column(BigInteger, nullable=True)
    seconds_powered = Column(Float, nullable=True)
    seconds_sorted = Column(Float, nullable=True)
    best_hour_ppm = Column(Float, nullable=True)

    registered = Column(Boolean, nullable=True)
    process_uptime_s = Column(Float, nullable=True)
    system_uptime_s = Column(Float, nullable=True)

    # Self-reported account identity (registered machines only): the machine's
    # local id, and {url, name, machine_id} per configured Hive account —
    # accounts[].machine_id joins to machines.id on this hive.
    local_machine_id = Column(String, nullable=True)
    accounts = Column(JSON_VARIANT, nullable=True)

    last_ping_payload = Column(JSON_VARIANT, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_devices_machine_id", "machine_id"),
        Index("ix_devices_install_id", "install_id"),
        Index("ix_devices_last_seen_at", "last_seen_at"),
    )
