from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    github_login: str | None = None
    avatar_url: str | None = None
    has_password: bool
    openrouter_configured: bool = False
    preferred_ai_model: str | None = None
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UpdateProfileRequest(BaseModel):
    display_name: str | None = None
    current_password: str | None = None
    new_password: str | None = None
    openrouter_api_key: str | None = None
    clear_openrouter_api_key: bool = False
    preferred_ai_model: str | None = None


class AdminUpdateUserRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None
