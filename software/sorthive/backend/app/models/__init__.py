from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


JSON_VARIANT = JSON().with_variant(JSONB, "postgresql")


from app.models.user import User  # noqa: E402, F401
from app.models.refresh_token import RefreshToken  # noqa: E402, F401
from app.models.machine import Machine  # noqa: E402, F401
from app.models.upload_session import UploadSession  # noqa: E402, F401
from app.models.sample import Sample  # noqa: E402, F401
from app.models.sample_review import SampleReview  # noqa: E402, F401
