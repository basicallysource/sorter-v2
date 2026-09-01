from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, Integer

from app.models import Base


class ServerStorageCache(Base):
    """Pre-computed object-store size accounting for the admin server-health page.

    Walking the whole object store (S3/Spaces lists every key) takes long enough
    that doing it inside the request blew past Cloudflare's proxy timeout (524).
    A background worker (app.services.server_health) walks the store on a slow
    cadence and upserts this single row; the API serves it directly so the page
    loads instantly. One row, fixed id=1, upserted in place — no history.
    """

    __tablename__ = "server_storage_cache"

    id = Column(Integer, primary_key=True, default=1)

    sample_images_bytes = Column(BigInteger, nullable=False, default=0)
    sample_images_files = Column(BigInteger, nullable=False, default=0)
    piece_images_bytes = Column(BigInteger, nullable=False, default=0)
    piece_images_files = Column(BigInteger, nullable=False, default=0)
    model_files_bytes = Column(BigInteger, nullable=False, default=0)
    model_files_files = Column(BigInteger, nullable=False, default=0)

    total_bytes = Column(BigInteger, nullable=False, default=0)
    total_files = Column(BigInteger, nullable=False, default=0)

    computed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
