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
from app.models.sorting_profile import SortingProfile  # noqa: E402, F401
from app.models.sorting_profile_version import SortingProfileVersion  # noqa: E402, F401
from app.models.sorting_profile_library_entry import SortingProfileLibraryEntry  # noqa: E402, F401
from app.models.sorting_profile_ai_message import SortingProfileAiMessage  # noqa: E402, F401
from app.models.machine_profile_assignment import MachineProfileAssignment  # noqa: E402, F401
