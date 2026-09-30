"""What an assistant needs to work on sorting profiles for someone: a skill
(instructions, as a Markdown file it can keep) to go with the API key the
person makes. No credential: the skill says nothing an API key would protect."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import get_current_user_or_api_key, get_db
from app.models.user import User
from app.models.user_api_key import UserApiKey

router = APIRouter(prefix="/api/agent", tags=["agent"])

SKILL_PATH = Path(__file__).resolve().parent.parent / "agent" / "sorting-profiles-skill.md"


def skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8").replace("{{BASE_URL}}", settings.public_app_url)


@router.get("/skill.md")
def get_sorting_profiles_skill() -> Response:
    return Response(
        content=skill_text(),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="SKILL.md"', "Cache-Control": "public, max-age=300"},
    )


@router.get("/whoami")
def whoami(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    """Who the credential is: the account, and for a key its name, scopes and
    the machines it is limited to (null: all the account's)."""
    key = None
    key_id = getattr(request.state, "api_key_id", None)
    if key_id is not None:
        row = db.query(UserApiKey).filter(UserApiKey.id == key_id).first()
        if row is not None:
            key = {"name": row.name, "scopes": row.scopes or [], "machine_ids": row.machine_ids}
    return {
        "account": {"id": str(current_user.id), "display_name": current_user.display_name, "email": current_user.email},
        "key": key,
        "hive": settings.public_app_url,
    }
