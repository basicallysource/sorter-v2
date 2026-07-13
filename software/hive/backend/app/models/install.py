from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, Index, Integer, String

from app.models import JSON_VARIANT, Base


class Install(Base):
    """One row per anonymous sorter install (status_ping.py on the machine).

    Deliberately NOT joined to a Machine / owner: the machine sends a random
    install_id and never its account-linked identity, so this table is the
    "anonymous fleet" view and is wiped independently via the public /forget
    endpoint. Columns cover the queryable fields (who, what version, where,
    how much); the whole raw ping is kept in last_payload for anything not
    promoted to a column.
    """

    __tablename__ = "installs"

    install_id = Column(String, primary_key=True)

    # created_at is client-reported (when the machine first generated its id);
    # first_seen_at / last_seen_at are server-stamped from actual pings.
    created_at = Column(DateTime(timezone=True), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    ping_count = Column(Integer, nullable=False, default=0)
    last_reason = Column(String, nullable=True)

    # Location is derived server-side from the connecting IP — coarse only, to
    # country/region granularity. Stored raw here; geo columns filled offline.
    last_ip = Column(String, nullable=True)
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

    # Set once the operator registers a Hive account (with their consent — see
    # the sorter status_ping._accountIdentities). machine_id is the install's own
    # local id; accounts is the list of {url, name, machine_id} for every account
    # this machine is registered to, so an install row joins to machines.id.
    machine_id = Column(String, nullable=True)
    accounts = Column(JSON_VARIANT, nullable=True)

    last_payload = Column(JSON_VARIANT, nullable=True)

    __table_args__ = (
        Index("ix_installs_last_seen_at", "last_seen_at"),
        Index("ix_installs_software_version", "software_version"),
        Index("ix_installs_country", "country"),
        Index("ix_installs_machine_id", "machine_id"),
    )
