from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String

from app.models import Base


class AccessWindow(Base):
    """Per-(role, entity) visibility window bounding what a non-admin can see of
    the accumulating piece-bbox dataset.

    A window is a contiguous slice of an entity ordered by ``created_at`` (id as
    tiebreak). ``anchor`` picks which end the slice hangs off:

      - ``oldest`` — slice counts from the oldest row. Because rows only ever
        append at the newest end, an oldest-anchored slice is effectively PINNED:
        the same rows stay in it until an admin moves ``offset``. Used for plain
        members so they see a small fixed sample and can't accumulate different
        slices by polling over time.
      - ``newest`` — slice counts from the newest row, so it ROLLS forward as new
        rows arrive. Used for reviewers so their (larger) working set tracks fresh
        incoming work automatically.

    Admins have no row and are unrestricted. Absent rows fall back to the code
    defaults in ``services.access_window`` (so the feature works before any admin
    config), and a size of 0 denies all — the safe default for an unknown role.
    """

    __tablename__ = "access_windows"

    role = Column(String, primary_key=True)
    entity = Column(String, primary_key=True)
    anchor = Column(String, nullable=False)
    # Mapped off reserved-ish SQL words to keep the DDL unambiguous.
    size = Column("window_size", Integer, nullable=False)
    offset = Column("window_offset", Integer, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint("anchor IN ('oldest', 'newest')", name="ck_access_windows_anchor"),
        CheckConstraint("window_size >= 0", name="ck_access_windows_size"),
        CheckConstraint("window_offset >= 0", name="ck_access_windows_offset"),
    )
