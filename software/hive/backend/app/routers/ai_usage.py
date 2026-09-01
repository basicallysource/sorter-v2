from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.user import User
from app.services.ai_usage import usage_summary

router = APIRouter(prefix="/api/ai", tags=["ai-usage"])


@router.get("/usage")
def get_ai_usage(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return usage_summary(db, user_id=current_user.id)
