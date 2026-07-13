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
from app.models.machine_set_progress import MachineSetProgress  # noqa: E402, F401
from app.models.machine_config_backup import MachineConfigBackup  # noqa: E402, F401
from app.models.detection_model import DetectionModel, DetectionModelVariant  # noqa: E402, F401
from app.models.user_api_key import UserApiKey  # noqa: E402, F401
from app.models.teacher_job import TeacherJob, TeacherJobItem  # noqa: E402, F401
from app.models.teacher_prompt import TeacherPrompt  # noqa: E402, F401
from app.models.machine_piece import MachinePiece  # noqa: E402, F401
from app.models.machine_piece_image import MachinePieceImage  # noqa: E402, F401
from app.models.machine_channel_crop import MachineChannelCrop  # noqa: E402, F401
from app.models.machine_sync_state import MachineSyncState  # noqa: E402, F401
from app.models.machine_stats_cache import MachineStatsCache  # noqa: E402, F401
from app.models.machine_daily_stats import MachineDailyStats  # noqa: E402, F401
from app.models.piece_color_label import PieceColorLabel  # noqa: E402, F401
from app.models.piece_crop_link import PieceCropLink, PieceCropLinkMember  # noqa: E402, F401
