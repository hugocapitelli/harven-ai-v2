from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SettingsUpdate(BaseModel):
    model_config = {"extra": "ignore"}

    institution_name: Optional[str] = None
    institution_logo: Optional[str] = None
    login_logo: Optional[str] = None
    login_bg: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    ai_api_key: Optional[str] = None
    max_upload_mb: Optional[int] = None
    enable_gamification: Optional[bool] = None
    enable_certificates: Optional[bool] = None
    enable_socratic: Optional[bool] = None


class SettingsResponse(BaseModel):
    id: Optional[str] = None
    institution_name: Optional[str] = None
    institution_logo: Optional[str] = None
    login_logo: Optional[str] = None
    login_bg: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    max_upload_mb: Optional[int] = None
    enable_gamification: Optional[bool] = None
    enable_certificates: Optional[bool] = None
    enable_socratic: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
