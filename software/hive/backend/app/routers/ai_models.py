from fastapi import APIRouter, Depends, Query

from app.deps import get_current_user
from app.models.user import User
from app.services.secrets import decrypt_secret
from app.services.openrouter_catalog import listCuratedModels

router = APIRouter(prefix="/api/ai", tags=["ai-models"])


@router.get("/models")
def list_ai_models(
    refresh: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
) -> dict:
    # The catalog endpoint is public, but sending the user's key keeps the
    # request attributed and avoids anonymous rate limits.
    api_key = decrypt_secret(current_user.openrouter_api_key_encrypted)
    return listCuratedModels(api_key=api_key, force_refresh=refresh)
