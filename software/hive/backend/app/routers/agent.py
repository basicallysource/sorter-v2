"""What an assistant needs to work on sorting profiles for someone: a skill
(instructions, as a Markdown file it can keep) to go with the API key the
person makes. No credential: the skill says nothing an API key would protect."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

from app.config import settings

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
